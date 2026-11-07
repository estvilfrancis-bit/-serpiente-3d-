import asyncio, math, random, secrets, time
from aiohttp import web, WSMsgType
from pathlib import Path

ROOT = Path(__file__).parent
rooms = {}

def orb():
    a=random.random()*math.tau; d=random.random()*35
    return {'id':secrets.token_hex(5),'x':round(math.cos(a)*d,2),'z':round(math.sin(a)*d,2),'h':random.random()}

async def index(request):
    return web.FileResponse(ROOT/'index.html')

async def ws_handler(request):
    room = request.query.get('sala','').upper()
    if not (4 <= len(room) <= 12 and room.isascii() and room.isalnum()):
        raise web.HTTPBadRequest(text='Código de sala inválido')
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
    await ws.prepare(request)
    r=rooms.setdefault(room, {'players':{}, 'orbs':[orb() for _ in range(12)], 'boss':None, 'picked':0, 'next':20, 'kills':0})
    if len(r['players'])>=8:
        await ws.send_json({'type':'error','message':'La sala está llena (máximo 8 jugadores).'}); await ws.close(); return ws
    pid=secrets.token_hex(5)
    p={'ws':ws,'x':0,'z':0,'a':0,'k':0,'level':1,'pick':0,'hits':0,'shots':0,'seen':0.0,'last_hit':0.0}
    r['players'][pid]=p
    await ws.send_json({'type':'welcome','id':pid,'room':room})
    try:
        async for message in ws:
            if message.type!=WSMsgType.TEXT: continue
            try:
                m=message.json()
                if not isinstance(m,dict): continue
                t=m.get('type')
                if t=='move':
                    x,z,a=map(float,(m['x'],m['z'],m['a']))
                    if not all(map(math.isfinite,(x,z,a))) or math.hypot(x,z)>41: continue
                    p.update(x=x,z=z,a=a,k=max(0,min(4,int(m.get('k',0)))),level=max(1,min(100,int(m.get('level',1)))))
                    taken=[o for o in r['orbs'] if math.hypot(x-o['x'],z-o['z'])<2.4]
                    if taken:
                        p['pick']+=len(taken);r['picked']+=len(taken)
                        for o in taken: r['orbs'].remove(o);r['orbs'].append(orb())
                    if r['boss'] is None and r['picked']>=r['next']:
                        r['boss']={'hp':100,'started':time.monotonic()};r['next']+=20
                elif t=='hit' and r['boss']:
                    now=time.monotonic()
                    if now-p['last_hit']<.25: continue
                    p['last_hit']=now;r['boss']['hp']-=min(20,3+p['level'])
                    if r['boss']['hp']<=0:
                        r['boss']=None;r['kills']+=1
                elif t=='shot':
                    p['shots']+=1
            except (ValueError, TypeError, KeyError, OverflowError): continue
    finally:
        r['players'].pop(pid,None)
        if not r['players'] and rooms.get(room) is r: rooms.pop(room,None)
    return ws

async def ticker(app):
    while True:
        await asyncio.sleep(.1)
        for room in list(rooms.values()):
            b=room['boss']; boss=None
            if b:
                t=time.monotonic()-b['started'];boss={'x':round(math.cos(t*.4)*16,2),'z':round(math.sin(t*.4)*16,2),'hp':max(0,b['hp'])}
            players=[{'id':pid,'x':p['x'],'z':p['z'],'a':p['a'],'k':p['k'],'shots':p['shots']} for pid,p in list(room['players'].items())]
            for pid,p in list(room['players'].items()):
                try: await p['ws'].send_json({'type':'state','players':players,'orbs':room['orbs'],'boss':boss,'pick':p['pick'],'kills':room['kills']})
                except (ConnectionError,RuntimeError): pass

async def start(app): app['ticker']=asyncio.create_task(ticker(app))
async def stop(app):
    app['ticker'].cancel()
    try: await app['ticker']
    except asyncio.CancelledError: pass
app=web.Application();app.router.add_get('/',index);app.router.add_get('/ws',ws_handler);app.on_startup.append(start);app.on_cleanup.append(stop)
if __name__=='__main__':
    import os
    web.run_app(app,host='0.0.0.0',port=int(os.environ.get('PORT','8080')))
