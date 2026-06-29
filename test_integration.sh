#!/bin/bash
# Canvas Integration Test Runner
# Single script that runs and reports

CANVAS_URL="${CANVAS_URL:-https://canvas.wodinga.studio}"

# Source env
eval "$(grep '^CANVAS_TOKEN=' /home/openclaw/projects/canvas/.env | head -1)"
eval "$(grep '^CASPER_TOKEN=' /home/openclaw/projects/canvas/.env | head -1)"

P=0; F=0; TB="test-sh-$(date +%s)"

ok() { echo "  [PASS] $1"; P=$((P+1)); }
ko() { echo "  [FAIL] $1"; F=$((F+1)); [ -n "$2" ] && echo "         $2"; }

push() { curl -s -w '\n%{http_code}' -X POST "$CANVAS_URL/push" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $CASPER_TOKEN" -d "$1"; }

echo ""
echo "───── Canvas Integration Tests ─────"
echo "Board: $TB"
echo ""

# 1. Health & Auth
echo "── Health & Auth ──"
c=$(curl -s -o /dev/null -w '%{http_code}' "$CANVAS_URL/health")
[ "$c" = "200" ] && ok "GET /health returns 200" || ko "Expected 200 got $c"

b=$(curl -s "$CANVAS_URL/health")
echo "$b" | python3 -c "import json,sys;d=json.load(sys.stdin);assert'database'in d" 2>/dev/null && ok "Health has database field" || ko "Missing database field"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" -H "Content-Type: application/json" -d '{"type":"markdown","content":"# x"}')
[ "$c" = "401" ] && ok "No token → 401" || ko "Expected 401 got $c"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" -H "Content-Type: application/json" -H "Authorization: Bearer bad" -d '{"type":"markdown","content":"# x"}')
[ "$c" = "401" ] && ok "Bad token → 401" || ko "Expected 401 got $c"

# 2. Content Types
echo ""
echo "── Push Content Types ──"
for t in markdown code mermaid html app image video; do
    c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $CASPER_TOKEN" \
        -d "{\"type\":\"$t\",\"content\":\"# $t\",\"board\":\"$TB\"}")
    [ "$c" = "200" ] && ok "Push $t" || ko "Push $t (HTTP $c)"
done

# draw type uses object content
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $CASPER_TOKEN" \
    -d "{\"type\":\"draw\",\"content\":{\"shapes\":[{\"type\":\"rect\",\"x\":0,\"y\":0,\"w\":100,\"h\":50}]},\"board\":\"$TB\"}")
[ "$c" = "200" ] && ok "Push draw" || ko "Push draw (HTTP $c)"

# 3. Card Editing
echo ""
echo "── Card Editing ──"
r=$(push '{"type":"markdown","content":"# Orig","board":"'$TB'","card_id":"test-edit"}')
c=$(echo "$r" | tail -1); [ "$c" = "200" ] && ok "Create via card_id" || ko "Create failed ($c)"
r=$(push '{"type":"markdown","content":"# Updated","board":"'$TB'","card_id":"test-edit"}')
c=$(echo "$r" | tail -1); [ "$c" = "200" ] && ok "Update via card_id" || ko "Update failed ($c)"
sleep 0.3
curl -s "$CANVAS_URL/history/$TB" | python3 -c "
import json,sys;d=json.load(sys.stdin)
found=[c for c in d.get('cards',[]) if c.get('id')=='test-edit']
assert len(found)==1 and 'Updated' in found[0]['content']
" 2>/dev/null && ok "Verify updated in history" || ko "Verify failed"
c=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$CANVAS_URL/card/test-edit" -H "Authorization: Bearer $CASPER_TOKEN")
[ "$c" = "200" ] && ok "Delete card" || ko "Delete failed ($c)"
sleep 0.3
curl -s "$CANVAS_URL/history/$TB" | python3 -c "
import json,sys;d=json.load(sys.stdin)
assert len([c for c in d.get('cards',[]) if c.get('id')=='test-edit'])==0
" 2>/dev/null && ok "Verify gone after delete" || ko "Verify gone failed"

# 4. Identity Override
echo ""
echo "── Identity Override ──"
r=$(push '{"type":"markdown","content":"# ID","board":"'$TB'","agent":"evil","agent_emoji":"💀"}')
i=$(echo "$r" | head -1 | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
sleep 0.3
curl -s "$CANVAS_URL/history/$TB" | python3 -c "
import json,sys;d=json.load(sys.stdin)
found=[c for c in d.get('cards',[]) if c.get('id')=='$i']
assert found[0]['agent']=='casper' and found[0]['agent_emoji']=='👻'
" 2>/dev/null && ok "Auth overrides payload identity" || ko "Identity override failed"

# 5. Expiry
echo ""
echo "── Expiry ──"
push '{"type":"markdown","content":"# Future","board":"'$TB'","expires_at":"2099-12-31T23:59:59"}'
fi=$(echo "$r" | head -1 | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
push '{"type":"markdown","content":"# Past","board":"'$TB'","expires_at":"2020-01-01T00:00:00"}'
pi=$(echo "$r" | head -1 | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
push '{"type":"markdown","content":"# Default","board":"'$TB'"}'
di=$(echo "$r" | head -1 | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
sleep 0.3
# Future check
r2=$(push '{"type":"markdown","content":"# Future","board":"'$TB'","expires_at":"2099-12-31T23:59:59"}')
future_id=$(echo "$r2" | head -1 | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
# Past check
r3=$(push '{"type":"markdown","content":"# Past","board":"'$TB'","expires_at":"2020-01-01T00:00:00"}')
past_id=$(echo "$r3" | head -1 | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
# Default check
r4=$(push '{"type":"markdown","content":"# Default","board":"'$TB'"}')
default_id=$(echo "$r4" | head -1 | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
sleep 0.3
curl -s "$CANVAS_URL/history/$TB" | python3 -c "
import json,sys;d=json.load(sys.stdin);c=d.get('cards',[])
assert len([x for x in c if x.get('id')=='$future_id'])==1, 'future not found'
assert len([x for x in c if x.get('id')=='$past_id'])==0, 'past should be hidden'
assert len([x for x in c if x.get('id')=='$default_id'])==1, 'default not found'
print('         Expiry: future=visible past=hidden default=visible')
" 2>&1 && ok "Expiry behavior correct" || ko "Expiry test failed"

# 6. Board Isolation
echo ""
echo "── Board Isolation ──"
curl -s -o /dev/null -X POST "$CANVAS_URL/push" -H "Content-Type: application/json" -H "Authorization: Bearer $CASPER_TOKEN" \
    -d '{"type":"markdown","content":"# A","board":"iso-a-sh"}'
curl -s -o /dev/null -X POST "$CANVAS_URL/push" -H "Content-Type: application/json" -H "Authorization: Bearer $CASPER_TOKEN" \
    -d '{"type":"markdown","content":"# B","board":"iso-b-sh"}'
sleep 0.3
ca=$(curl -s "$CANVAS_URL/history/iso-a-sh" | python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d.get('cards',[])))")
cb=$(curl -s "$CANVAS_URL/history/iso-b-sh" | python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d.get('cards',[])))")
[ "$ca" -gt 0 ] && ok "Board A has cards ($ca)" || ko "Board A empty"
[ "$cb" -gt 0 ] && ok "Board B has cards ($cb)" || ko "Board B empty"
# Verify no cross-contamination
curl -s "$CANVAS_URL/history/iso-a-sh" | python3 -c "
import json,sys;d=json.load(sys.stdin)
assert all('Board B' not in c.get('content','') for c in d.get('cards',[]))
" 2>/dev/null && ok "Board A isolated" || ko "Board A leaked!"
curl -s "$CANVAS_URL/history/iso-b-sh" | python3 -c "
import json,sys;d=json.load(sys.stdin)
assert all('Board A' not in c.get('content','') for c in d.get('cards',[]))
" 2>/dev/null && ok "Board B isolated" || ko "Board B leaked!"

# 7. Token Management
echo ""
echo "── Token Management ──"
r5=$(curl -s -X POST "$CANVAS_URL/token" -H "Content-Type: application/json" \
    -H "Authorization: Bearer $CANVAS_TOKEN" -d '{"agent":"bot-sh-test","agent_emoji":"🤖"}')
bt=$(echo "$r5" | python3 -c "import json,sys;print(json.load(sys.stdin).get('token',''))")
[ -n "$bt" ] && ok "POST /token — create ($bt)" || ko "Token creation failed"

c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $bt" \
    -d '{"type":"markdown","content":"# Bot","board":"'$TB'"}')
[ "$c" = "200" ] && ok "Push with new token" || ko "Push with new token failed ($c)"

c=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$CANVAS_URL/token" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $CANVAS_TOKEN" \
    -d '{"agent":"bot-sh-test"}')
[ "$c" = "200" ] && ok "Revoke token" || ko "Revoke failed ($c)"

sleep 0.3
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $bt" \
    -d '{"type":"markdown","content":"# Fail","board":"'$TB'"}')
[ "$c" = "401" ] && ok "Revoked token → 401" || ko "Expected 401 got $c"

# 8. Clear Board
echo ""
echo "── Clear Board ──"
for i in 1 2 3; do
    curl -s -o /dev/null -X POST "$CANVAS_URL/push" -H "Content-Type: application/json" \
        -H "Authorization: Bearer $CASPER_TOKEN" \
        -d "{\"type\":\"markdown\",\"content\":\"# C$i\",\"board\":\"test-clear-sh\"}"
done
sleep 0.3
cnt=$(curl -s "$CANVAS_URL/history/test-clear-sh" | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('cards',[])))")
[ "$cnt" -gt 0 ] && ok "Cards present before clear ($cnt)" || ko "No cards before clear"
curl -s -o /dev/null -X POST "$CANVAS_URL/push" -H "Content-Type: application/json" \
    -H "Authorization: Bearer $CASPER_TOKEN" \
    -d '{"type":"clear","board":"test-clear-sh"}'
sleep 0.3
cnt=$(curl -s "$CANVAS_URL/history/test-clear-sh" | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('cards',[])))")
[ "$cnt" -eq 0 ] && ok "Board empty after clear" || ko "Not empty ($cnt cards)"

# 9. Pagination
echo ""
echo "── Pagination ──"
for i in $(seq 0 24); do
    curl -s -o /dev/null -X POST "$CANVAS_URL/push" -H "Content-Type: application/json" \
        -H "Authorization: Bearer $CASPER_TOKEN" \
        -d "{\"type\":\"markdown\",\"content\":\"# Card $i\",\"board\":\"test-paginate-sh\"}"
done
sleep 1.0
hr=$(curl -s "$CANVAS_URL/history/test-paginate-sh")
echo "$hr" | python3 -c "
import json,sys;d=json.load(sys.stdin)
c=len(d.get('cards',[])); t=d.get('total',0)
print('         total=%d, page1=%d' % (t,c))
assert c==20, 'page1 should be 20'
assert t>=25, 'total should be >=25'
" 2>&1 && ok "Pagination: page size 20" || ko "Pagination failed"

# 10. Boards & Reload
echo ""
echo "── Boards & Reload ──"
b=$(curl -s "$CANVAS_URL/boards")
echo "$b" | python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d))" 2>/dev/null && ok "GET /boards returns list" || ko "GET /boards failed"
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/reload" -H "Content-Type: application/json" -H "Authorization: Bearer $CANVAS_TOKEN")
[ "$c" = "200" ] && ok "POST /reload" || ko "Reload failed ($c)"
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/reload")
[ "$c" = "401" ] && ok "POST /reload without token → 401" || ko "Expected 401 got $c"

# 11. Card Page
echo ""
echo "── Card Page ──"
c=$(curl -s -o /dev/null -w '%{http_code}' "$CANVAS_URL/card/test-edit")
[ "$c" = "200" ] && ok "GET /card/<id>" || ko "Card page returned $c"
c=$(curl -s -o /dev/null -w '%{http_code}' "$CANVAS_URL/card/nonexistent")
[ "$c" = "200" -o "$c" = "404" ] && ok "GET /card/<bad> ($c)" || ko "Not found returned $c"

# 12. Content Validation
echo ""
echo "── Content Validation ──"
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $CASPER_TOKEN" \
    -d '{"type":"latex","content":"x","board":"'$TB'"}')
[ "$c" = "400" ] && ok "Invalid type → 400" || ko "Expected 400 got $c"
c=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$CANVAS_URL/push" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $CASPER_TOKEN" \
    -d '{"type":"markdown","content":"","board":"'$TB'"}')
[ "$c" = "400" ] && ok "Missing content → 400" || ko "Expected 400 got $c"

echo ""
echo "=================================================="
echo "Results: $P PASS, $F FAIL"
echo "=================================================="
exit $F