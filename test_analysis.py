import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from webapp import app

with app.test_client() as client:
    r = client.get('/api/deep_analysis/EURUSD')
    d = json.loads(r.data)
    
    print(f"\n{'='*70}")
    print(f"  ANALYSE INSTITUTIONNELLE: {d['symbol']}  |  Prix: {d['price']}")
    print(f"{'='*70}")
    
    for c in d['criteria']:
        icon = c.get('icon', '')
        print(f"\n  #{c['id']} {c['name']} ({icon}) -> {c['direction'].upper()}")
        print(f"     {c['detail']}")
    
    print(f"\n{'='*70}")
    print(f"  VERDICT: {d['verdict_text']}")
    print(f"  Confiance: {d.get('confidence', 0)}%")
    print(f"  {d['golden_rule']}")
    print(f"  Context: {d.get('context', '')}")
    
    scores = d.get('scores_detail', {})
    if scores:
        print(f"\n  SCORES CONFLUENCE:")
        for k, v in scores.items():
            arrow = "^" if v > 0 else ("v" if v < 0 else "-")
            print(f"    {arrow} {k}: {v:+.1f}")
        print(f"    TOTAL: {d.get('confluence_score', 0):+.1f}")
    
    pt = d.get('price_targets', {})
    if pt.get('stop_loss'):
        print(f"\n  OBJECTIFS:")
        print(f"    Entry: {pt['entry']}")
        print(f"    SL:    {pt['stop_loss']}  (risque: {pt['risk_pct']}%)")
        print(f"    TP1:   {pt['tp1']}  ({pt['rr1_pct']}%)")
        print(f"    TP2:   {pt['tp2']}  ({pt['rr2_pct']}%)")
        print(f"    TP3:   {pt['tp3']}  ({pt['rr3_pct']}%)")
        print(f"    Conseil: {pt['conseil']}")
    
    print(f"\n{'='*70}\n")
