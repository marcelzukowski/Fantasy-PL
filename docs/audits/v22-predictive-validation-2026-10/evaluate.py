"""Read-only V22 evidence join; writes only audit outputs beside this script.

Primary rule is fixed before outcomes: latest canonical run per GW with matching
artifact hashes, local official pre-cutoff deadline, and a pre-deadline archive
reference to the exact bundle bytes. Local timestamps are operational evidence,
not externally notarized proof. No network, engine execution or database writes.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import mean
from inventory import ROOT, HERE

INPUTS = {}

def load(path):
    path = Path(path)
    data = path.read_bytes()
    INPUTS[str(path.relative_to(ROOT)).replace('\\', '/')] = sha256(data).hexdigest()
    return json.loads(data)

def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def metrics(rows, prediction='xp', actual='points'):
    errors = [r[prediction]-r[actual] for r in rows]
    return {'n': len(errors), 'mae': mean(map(abs, errors)) if errors else None,
            'rmse': math.sqrt(mean(e*e for e in errors)) if errors else None,
            'bias': mean(errors) if errors else None}

def ranks(values):
    ordered = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0]*len(values)
    start = 0
    while start < len(ordered):
        stop = start+1
        while stop < len(ordered) and values[ordered[stop]] == values[ordered[start]]:
            stop += 1
        for i in ordered[start:stop]:
            result[i] = (start+stop-1)/2
        start = stop
    return result

def spearman(rows):
    x, y = ranks([r['xp'] for r in rows]), ranks([r['points'] for r in rows])
    if len(x) < 2:
        return None
    dx, dy = [v-mean(x) for v in x], [v-mean(y) for v in y]
    denominator = math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    return sum(a*b for a,b in zip(dx,dy))/denominator if denominator else None

def selfcheck():
    m = metrics([{'xp': 1, 'points': 3}, {'xp': 5, 'points': 3}])
    assert m == {'n': 2, 'mae': 2, 'rmse': 2, 'bias': 0}
    assert ranks([2, 2, 8]) == [0.5, 0.5, 2]
    assert abs(spearman([{'xp':1,'points':2},{'xp':2,'points':4}])-1) < 1e-12
    assert metrics([])['mae'] is None
    assert spearman([{'xp':1,'points':2},{'xp':1,'points':4}]) is None
    assert abs(mean((p-y)**2 for p,y in ((.8,1),(.2,0)))-.04)<1e-12
    assert abs(spearman([{'xp':1,'points':1},{'xp':1,'points':2},{'xp':3,'points':3}])-math.sqrt(.75))<1e-12
    assert utc('2026-10-10T10:00:00Z') == utc('2026-10-10T12:00:00+02:00')

def main():
    selfcheck()
    inventory = load(HERE/'inventory.json')
    raw = defaultdict(list)
    raw_failures = []
    for kind in ('bootstrap_static', 'event_live', 'element_summary'):
        for path in sorted((ROOT/'data/raw/official_fpl_api'/kind).glob('*/*/snapshot.metadata.json')):
            meta = load(path)
            payload = path.parent/'payload.bin'
            body = payload.read_bytes()
            digest = sha256(body).hexdigest()
            INPUTS[str(payload.relative_to(ROOT)).replace('\\', '/')] = digest
            if digest != meta['checksum']:
                raw_failures.append(str(path.relative_to(ROOT)))
                continue
            raw[kind].append((meta, json.loads(body)))
    latest_boot = max(raw['bootstrap_static'], key=lambda x: utc(x[0]['retrieved_at']))
    final_events = {e['id']: e for e in latest_boot[1]['events']}
    latest_identity = {str(e['id']): e for e in latest_boot[1]['elements']}
    outcomes = {}
    for meta, body in raw['event_live']:
        gw = int(meta['source_record_id'])
        event = final_events.get(gw, {})
        if not event.get('finished') or not event.get('data_checked'):
            continue
        old = outcomes.get(gw)
        if old is None or utc(meta['retrieved_at']) > utc(old[0]['retrieved_at']):
            outcomes[gw] = (meta, {str(e['id']): e['stats'] for e in body['elements']})
    archives = []
    for item in inventory['archives']:
        path = ROOT/item['path']
        case = load(path)
        ref = case.get('projection_bundle', {})
        archives.append({'path':item['path'], 'created':case['archive_created_at'],
                         'deadline':case['official_deadline'], 'gw':case['planning_gameweek'],
                         'bundle_sha256':ref.get('sha256'), 'bundle_ref':ref,
                         'status':case.get('context_verification_status')})
    snapshots = []
    for item in inventory['manifests']:
        if item.get('simulator') != 'fixture_simulator_v22_lineup_coherent_logit':
            continue
        path = ROOT/item['path']
        manifest = load(path)
        run = path.parent
        bundle_path = run/'shadow_projection_bundle.json'
        bundle = load(bundle_path) if bundle_path.exists() else None
        digest = INPUTS.get(str(bundle_path.relative_to(ROOT)).replace('\\','/'))
        failures = []
        for label, ref in manifest.get('artifacts', {}).items():
            target = run/ref['path']
            try:
                actual = sha256(target.read_bytes()).hexdigest()
                INPUTS[str(target.relative_to(ROOT)).replace('\\','/')] = actual
                if actual != ref['sha256']:
                    failures.append(label+':HASH_MISMATCH')
            except OSError as exc:
                failures.append(label+':'+type(exc).__name__)
        gw, stamp = item['gw'], utc(item['prediction_timestamp'])
        context = load(run/'prediction_context.json') if (run/'prediction_context.json').exists() else {}
        boots = [(meta,body) for meta,body in raw['bootstrap_static']
                 if utc(meta['retrieved_at']) <= stamp and any(e['id']==gw for e in body['events'])]
        source = max(boots,key=lambda x:utc(x[0]['retrieved_at'])) if boots else None
        event = next((e for e in source[1]['events'] if e['id']==gw), None) if source else None
        deadline = event['deadline_time'] if event else None
        if context.get('official_deadline') and deadline != context['official_deadline'].replace('+00:00','Z'):
            # Normalize equivalent ISO timestamp representations.
            if not deadline or utc(context['official_deadline']) != utc(deadline):
                failures.append('DEADLINE_DISAGREEMENT')
        references = [a for a in archives if a['bundle_sha256']==digest
                      and utc(a['created']) < utc(a['deadline']) and a['gw']==gw
                      and a['status']=='PASS']
        canonical = item['path'].startswith('data/processed/predictions/')
        reasons = []
        if not canonical: reasons.append('diagnostic/replay/copy outside canonical prediction runs')
        if not manifest.get('artifacts'): reasons.append('no artifact hash manifest')
        if failures: reasons.append('artifact integrity failure')
        if not deadline: reasons.append('no local pre-cutoff official deadline source')
        elif stamp >= utc(deadline): reasons.append('prediction timestamp at/after deadline')
        if not references: reasons.append('no pre-deadline archive reference to exact bundle hash')
        if gw not in outcomes: reasons.append('no locally verified final GW outcomes')
        row = dict(path=item['path'],gw=gw,season=item['season'],generated=item['prediction_timestamp'],
                   simulations=item['simulations'],mode=item['simulation_mode'],bundle_sha256=digest,
                   artifacts=len(manifest.get('artifacts',{})),integrity_failures=failures,deadline=deadline,
                   deadline_snapshot=source[0]['snapshot_id'] if source else None,
                   archive_references=[a['path'] for a in references],eligible=not reasons,reasons=reasons)
        snapshots.append(row)
    selected = {}
    for row in snapshots:
        if row['eligible'] and (row['gw'] not in selected or utc(row['generated']) > utc(selected[row['gw']]['generated'])):
            selected[row['gw']] = row
    rows, exclusions = [], []
    for gw, snap in sorted(selected.items()):
        run = (ROOT/snap['path']).parent
        bundle = load(run/'shadow_projection_bundle.json')
        players = load(run/'current_players.json')
        identities = {r['player_id']:r for r in players}
        assert len(identities)==len(players)
        meta, actuals = outcomes[gw]
        for projection in bundle['projections']:
            player = identities.get(projection['player_id'])
            reason = None
            provider = str(player['provider_id']) if player else None
            latest = latest_identity.get(provider)
            if not player or not latest or player['provider_payload']['code'] != latest['code']:
                reason = 'missing/mismatched official ID and stable code'
            elif provider not in actuals:
                reason = 'missing explicit event-live outcome (never imputed zero)'
            target = next((g for g in projection['gameweeks'] if g['target_gameweek']==gw),None)
            if target is None: reason = 'missing target GW projection'
            if reason:
                exclusions.append(dict(gw=gw,player_id=projection['player_id'],reason=reason))
                continue
            stats = actuals[provider]
            record = dict(gw=gw,player_id=projection['player_id'],provider_id=provider,
                          name=player['display_name'],position=player['position'],xp=target['expected_points'],
                          predicted_minutes=target['expected_minutes'],points=stats['total_points'],minutes=stats['minutes'],
                          goals=stats['goals_scored'],assists=stats['assists'],
                          fixtures=target['fixture_count'],freshness_hours=(utc(snap['deadline'])-utc(snap['generated'])).total_seconds()/3600)
            record.update({k:v for k,v in target.items() if k.startswith('p_')})
            # Baselines use the latest hash-verified event-live snapshot known at forecast time.
            historical = {}
            for hmeta, hbody in raw['event_live']:
                previous = int(hmeta['source_record_id'])
                if previous >= gw or utc(hmeta['retrieved_at']) > utc(snap['generated']): continue
                boots=[body for bmeta,body in raw['bootstrap_static'] if utc(bmeta['retrieved_at'])<=utc(snap['generated'])]
                # Require a pre-cutoff official completion observation, not hindsight finality.
                if not any(e['id']==previous and e.get('finished') and e.get('data_checked') for body in boots for e in body['events']): continue
                if previous not in historical or utc(hmeta['retrieved_at']) > utc(historical[previous][0]['retrieved_at']):
                    historical[previous]=(hmeta,hbody)
            history = []
            for previous, (_, body) in sorted(historical.items()):
                match = next((e['stats'] for e in body['elements'] if str(e['id'])==provider), None)
                if match is not None: history.append((previous,match))
            if history:
                record['previous_gw'] = history[-1][1]['total_points']
                recent = history[-3:]
                record['recent_mean'] = mean(h['total_points'] for _,h in recent)
                mins = sum(h['minutes'] for _,h in recent)
                if mins > 0:
                    record['minutes_aware'] = sum(h['total_points'] for _,h in recent)/mins*record['predicted_minutes']
                record['baseline_gws']=[g for g,_ in recent]
            rows.append(record)
    result = dict(raw_counts={k:len(v) for k,v in raw.items()},raw_hash_failures=raw_failures,
                  latest_outcome_bootstrap=latest_boot[0],final_outcome_gws=sorted(outcomes),archives=archives,
                  snapshots=snapshots,selected=list(selected.values()),rows=rows,row_exclusions=exclusions,
                  points=metrics(rows),minutes=metrics(rows,'predicted_minutes','minutes'),
                  by_gw={g:metrics([r for r in rows if r['gw']==g]) for g in selected},
                  by_position={p:metrics([r for r in rows if r['position']==p]) for p in ('GK','DEF','MID','FWD')},
                  baselines={})
    for name in ('previous_gw','recent_mean','minutes_aware'):
        matched = [r for r in rows if name in r]
        result['baselines'][name]={'baseline':metrics(matched,name),'v22_matched':metrics(matched)}
    for field, cuts in (('xp',(0,2,4,6,8,math.inf)),('predicted_minutes',(0,1,30,60,80,math.inf))):
        result['by_'+field]={f'[{lo},{hi})':metrics([r for r in rows if lo<=r[field]<hi]) for lo,hi in zip(cuts,cuts[1:])}
    result['ranking']={}
    for gw in selected:
        group=[r for r in rows if r['gw']==gw]
        top=sorted(group,key=lambda r:(-r['xp'],r['player_id']))[:20]
        result['ranking'][gw]={'spearman_all':spearman(group),'spearman_top20':spearman(top),
                               'top20_mean_actual':mean(r['points'] for r in top) if top else None,
                               'top5':sorted(group,key=lambda r:(-r['xp'],r['player_id']))[:5]}
    result['calibration']={}
    for threshold in (5,8,10,15):
        name=f'p_{threshold}_plus'
        matched=[r for r in rows if isinstance(r.get(name),(int,float))]
        bins={}
        for low,high in ((0,.1),(.1,.25),(.25,.5),(.5,.75),(.75,1.000001)):
            group=[r for r in matched if low<=r[name]<high]
            if group: bins[f'{low}-{min(high,1)}']={'n':len(group),'predicted':mean(r[name] for r in group),'observed':mean(r['points']>=threshold for r in group)}
        result['calibration'][name]={'n':len(matched),'brier':mean((r[name]-(r['points']>=threshold))**2 for r in matched) if matched else None,'bins':bins}
    (HERE/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    (HERE/'input-hashes.json').write_text(json.dumps(INPUTS,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('raw_counts','raw_hash_failures','final_outcome_gws','selected','points','minutes','by_gw','by_position','baselines')},indent=2))
    print('SNAPSHOTS')
    for s in snapshots: print(s['path'],s['gw'],s['integrity_failures'],s['reasons'])
    print('ARCHIVES',json.dumps(archives,indent=2))

if __name__ == '__main__':
    main()
