"""Render the profile's original SVG console panels from a public GitHub snapshot."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BG, SURFACE, BORDER = '#080c12', '#0e1621', '#253448'
WHITE, BLUE, MUTED = '#ecf3ff', '#75baff', '#8b9fb8'
PALETTE = [BLUE, '#a6d3ff', '#d8eaff', '#4e8ed8', '#a4c8eb', '#789dc4']
FONT = "'IBM Plex Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', monospace"
CSS = '''
text{font-family:FONT}
.pulse{animation:pulse 2.8s ease-in-out infinite}
.cursor{animation:blink 1.2s step-end infinite}
.orbit{transform-origin:80px 80px;animation:orbit 32s linear infinite}
.scan{animation:scan 9s linear infinite}
.boot{animation:boot 16s linear infinite;animation-delay:var(--delay,0s)}
.meter{transform-box:fill-box;transform-origin:left;animation:meter 1.2s ease-out both}
.rowlight{animation:rowlight 10s ease-in-out infinite;animation-delay:var(--delay,0s)}
.tick{opacity:0;animation:tick 15s linear infinite;animation-delay:var(--delay,0s)}
.tick.first{opacity:1}
.hexlight{animation:hexlight 12s steps(7,end) infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
@keyframes orbit{to{transform:rotate(360deg)}}
@keyframes scan{from{transform:translateY(-40px)}to{transform:translateY(440px)}}
@keyframes boot{0%,3%{opacity:.16}8%,85%{opacity:1}92%,100%{opacity:.16}}
@keyframes meter{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes rowlight{0%,8%,100%{opacity:0}15%,28%{opacity:.12}35%,95%{opacity:0}}
@keyframes tick{0%,29%{opacity:1}33%,100%{opacity:0}}
@keyframes hexlight{from{transform:translateY(0)}to{transform:translateY(196px)}}
@media(prefers-reduced-motion:reduce){
 .pulse,.cursor,.orbit,.scan,.boot,.meter,.rowlight,.tick,.hexlight{animation:none!important}
 .scan,.rowlight,.hexlight{display:none}.tick{opacity:0}.tick.first{opacity:1}
}
'''.replace('FONT', FONT)


def e(value):
    return escape(str(value), quote=True)


def short(value, limit):
    value = str(value or '').replace('\n', ' ').replace('\r', ' ')
    return value if len(value) <= limit else value[:limit-1] + '…'


def txt(x, y, value, size=14, color=WHITE, extra=''):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {extra}>{e(value)}</text>'


def rect(x, y, w, h, fill=SURFACE, extra=''):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" {extra}/>'


def line(x1, y1, x2, y2, color=BORDER, extra=''):
    return f'<path d="M{x1} {y1}H{x2}" stroke="{color}" {extra}/>' if y1 == y2 else f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{color}" {extra}/>'


def wrap(body, width, height, title, desc, panel=True):
    start = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{e(title)}</title><desc id="desc">{e(desc)}</desc>
<defs><style>{CSS}</style>
<pattern id="noise" width="4" height="4" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".45" fill="{BLUE}" opacity=".065"/></pattern>
<pattern id="lines" width="4" height="4" patternUnits="userSpaceOnUse"><path d="M0 3H4" stroke="#000" opacity=".15"/></pattern>
<linearGradient id="scan"><stop stop-color="{BLUE}" stop-opacity="0"/><stop offset=".5" stop-color="{BLUE}" stop-opacity=".09"/><stop offset="1" stop-color="{BLUE}" stop-opacity="0"/></linearGradient>
<clipPath id="bounds"><rect width="{width}" height="{height}"/></clipPath></defs>
<g clip-path="url(#bounds)">{rect(0,0,width,height,BG)}{rect(0,0,width,height,'url(#noise)')}'''
    end = rect(0,0,width,height,'url(#lines)', 'pointer-events="none"')
    if panel:
        end += rect(.5,.5,width-1,height-1,'none',f'stroke="{BORDER}"')
    return start + body + end + '</g></svg>\n'


def head(width, path, right='', mobile=False):
    size = 16 if mobile else 13
    out = rect(0,0,width,36,SURFACE) + line(0,36,width,36)
    out += txt(16,24,path,size,BLUE)
    if right:
        out += txt(width-16,24,right,13 if mobile else 11,MUTED,'text-anchor="end"')
    return out


def foot(width, height, left, right='', mobile=False):
    y=height-29
    out = line(0,y,width,y) + txt(16,y+19,left,12 if mobile else 11,MUTED)
    if right:
        out += txt(width-16,y+19,right,11,MUTED,'text-anchor="end"')
    return out


def mark():
    body = '<g class="orbit"><circle cx="80" cy="80" r="66" fill="none" stroke="#253448" stroke-dasharray="2 7"/><path d="M80 14A66 66 0 0 1 146 80" fill="none" stroke="#75baff"/><rect x="143" y="77" width="6" height="6" fill="#ecf3ff"/></g>'
    body += rect(39,39,82,82,BG,f'stroke="{BLUE}"')
    for pos in range(49,117,11):
        body += line(pos,31,pos,38,MUTED)+line(pos,122,pos,129,MUTED)+line(31,pos,38,pos,MUTED)+line(122,pos,129,pos,MUTED)
    body += txt(53,87,'lc',36,WHITE,'font-weight="700"') + txt(80,109,'1802',9,BLUE,'text-anchor="middle" letter-spacing="3"')
    body += '<circle class="pulse" cx="110" cy="49" r="2.5" fill="#75baff"/>'
    return wrap(body,160,160,'Luca microchip monogram','An lc monogram inside a blue microchip with a slowly orbiting signal.',False)


def hero(data, mobile=False):
    w,h=(480,352) if mobile else (960,276)
    body = txt(28,29,'USER SPACE / PERSONAL SYSTEM',12,BLUE,'letter-spacing="1.5"')
    for n,col in enumerate([WHITE,'#d8eaff','#a6d3ff',BLUE,'#4e8ed8','#253448']):
        body += rect(28,55+n*9,8,7,col)
    body += txt(54,101,'luca-1802',48 if mobile else 61,WHITE,'font-weight="700" letter-spacing="-2"')
    body += line(54,116,443 if mobile else 555,116,BLUE)
    rows=[('FOCUS','software / automation'),('STACK','Python · TypeScript · React'),('BASE','Germany'),('TOOLS','Docker · Git · CLI')]
    for n,(label,value) in enumerate(rows):
        y=153+n*(30 if mobile else 23)
        body += txt(28 if mobile else 54,y,label,14 if mobile else 12,MUTED)
        body += txt(110 if mobile else 147,y,value,16 if mobile else 14)
    cy=303 if mobile else 248
    body += txt(28 if mobile else 54,cy,'> ./luca --init',17 if mobile else 15,BLUE)
    body += rect(183 if mobile else 192,cy-14,8,17,WHITE,'class="cursor"')
    if mobile:
        body += txt(452,333,'PUBLIC PROFILE',11,MUTED,'text-anchor="end" letter-spacing="1"')
    else:
        body += rect(641,54,291,190,'none',f'stroke="{BORDER}"')+rect(641,54,291,27,SURFACE)
        body += txt(654,72,'session.info',12,BLUE)+txt(918,72,'0x1802',11,MUTED,'text-anchor="end"')
        status=[('user',data['login']),('repos',str(len(data['repos'])).zfill(2)+' public'),('branch','main'),('created',data['profile']['created_at'][:4]),('mode','read / build / repeat'),('refresh','daily')]
        for n,(k,v) in enumerate(status):
            body += txt(654,102+n*23,k,12,MUTED)+txt(726,102+n*23,v,12)
    body += rect(0,0,w,32,'url(#scan)','class="scan" pointer-events="none"')
    return wrap(body,w,h,'luca-1802 / user space','Luca in Germany. Software and automation. Python, TypeScript, React, Docker, Git and CLI tools. Animated profile terminal.')


def stats(data, mobile=False):
    w,h=(480,295) if mobile else (960,180)
    own=[r for r in data['repos'] if not r['is_fork']]
    values=[('STARS',sum(r['stars'] for r in own),'original repositories'),('REPOSITORIES',len(data['repos']),'public repositories'),('FOLLOWERS',data['profile']['followers'],'on GitHub'),('LANGUAGES',len(data['languages']),'original source code')]
    body=head(w,'/sys/github/stats','PUBLIC SNAPSHOT' if not mobile else '',mobile)
    for n,(label,value,sub) in enumerate(values):
        x=14+(n%2)*232 if mobile else 14+n*236
        y=48+(n//2)*103 if mobile else 48
        cw=218 if mobile else 220
        body += rect(x,y,cw,92,SURFACE)+rect(x,y,2,92,BLUE)
        body += txt(x+14,y+20,label,12 if mobile else 10,MUTED,'letter-spacing="1.3"')
        body += txt(x+14,y+61,str(value).zfill(2),38,WHITE)
        body += txt(x+cw-12,y+81,sub,10,MUTED,'text-anchor="end"')
        body += f'<circle class="pulse" cx="{x+cw-12}" cy="{y+15}" r="2" fill="{BLUE}"/>'
    body += foot(w,h,'updated '+data['sampled_at'][:10],'' if mobile else 'luca-1802@github',mobile)
    return wrap(body,w,h,'GitHub statistics',f"{values[0][1]} stars on original repositories, {values[1][1]} public repositories, {values[2][1]} followers, {values[3][1]} source languages. Sampled {data['sampled_at']}.")


def ticker(mobile=False):
    w,h=(480,136) if mobile else (960,92)
    body=head(w,'/proc/focus','ROTATING / 15s' if not mobile else '',mobile)
    rows=[('SELF-HOSTED','password-manager'),('AUTOMATION','file-organizer'),('COMMAND LINE','weather-cli')]
    for n,(tag,value) in enumerate(rows):
        delay=-15+n*5
        body += f'<g class="tick {"first" if n==0 else ""}" style="--delay:{delay}s">'
        body += txt(20,67 if mobile else 70,tag,13,BLUE,'letter-spacing="1"')
        body += txt(20 if mobile else 217,108 if mobile else 70,value,24 if mobile else 21)
        body += '</g>'
    body += rect(w-27,h-25,7,12,BLUE,'class="cursor"')
    return wrap(body,w,h,'Current focus','Rotating project focus: self-hosted password-manager, file-organizer automation, and weather-cli.')


def boot(mobile=False):
    w,h=(480,316) if mobile else (960,263)
    body=head(w,'profile.init()','BOOT SEQUENCE' if not mobile else '',mobile)
    rows=[('00.018','mount','/home/luca'),('00.042','load','Python · TypeScript'),('00.106','attach','React · Docker · Git'),('00.184','index','public repositories'),('00.256','start','interactive session'),('00.512','ready','luca-1802@github')]
    for n,(tm,cmd,value) in enumerate(rows):
        y=70+n*(32 if mobile else 27)
        body += f'<g class="boot" style="--delay:{n*.6}s">'
        body += txt(17,y,tm,14 if mobile else 12,MUTED)
        body += txt(89 if mobile else 100,y,cmd.ljust(7),15 if mobile else 14,BLUE)
        body += txt(171 if mobile else 220,y,value,15 if mobile else 14)
        if not mobile:
            body += txt(931,y,'[ OK ]',12,MUTED,'text-anchor="end"')
        body += '</g>'
    body += foot(w,h,'profile boot animation','LOOP / 16s' if not mobile else '',mobile)
    return wrap(body,w,h,'Profile boot sequence','A decorative boot sequence introduces Luca’s software tools, public repositories and GitHub profile. This is an animation, not a build or health report.')


def hexdump(mobile=False):
    raw=b'luca-1802\x00Python\x00TypeScript\x00React\x00Docker\x00Git\x00CLI\x00'
    step=8 if mobile else 16
    rows=[raw[n:n+step] for n in range(0,len(raw),step)]
    w,h=(480,93+len(rows)*29) if mobile else (960,101+len(rows)*29)
    body=head(w,'hexdump -C profile.bin',str(len(raw))+' BYTES' if not mobile else '',mobile)
    body += rect(10,52,w-20,27,BLUE,'class="hexlight" opacity=".07"')
    for n,chunk in enumerate(rows):
        y=72+n*29
        body += txt(15,y,f'{n*step:04x}' if mobile else f'{n*step:08x}',15 if mobile else 13,MUTED)
        body += txt(73 if mobile else 123,y,' '.join(f'{v:02x}' for v in chunk),16 if mobile else 14,BLUE)
        chars=''.join(chr(v) if 32<=v<127 else '.' for v in chunk)
        if not mobile:
            body += txt(714,y,'|'+chars+'|',13)
    body += foot(w,h,'ASCII / UTF-8','profile identity bytes' if not mobile else '',mobile)
    return wrap(body,w,h,'Profile hex dump','A decorative hexadecimal encoding of luca-1802, Python, TypeScript, React, Docker, Git and CLI.')


def repos(data, mobile=False):
    rows=[r for r in data['repos'] if not r['is_fork'] and r['name'].lower()!=data['login'].lower()][:6]
    w,h=(480,88+max(1,len(rows))*77) if mobile else (960,124+max(1,len(rows))*38)
    body=head(w,'top --public --no-forks','REPOSITORY TABLE' if not mobile else '',mobile)
    if not mobile:
        body += txt(18,68,'REPOSITORY',12,MUTED)+txt(434,68,'LANGUAGE',12,MUTED)+txt(638,68,'STARS',12,MUTED)+txt(742,68,'FORKS',12,MUTED)+txt(835,68,'PUSHED',12,MUTED)
        body += line(12,80,948,80)
    for n,r in enumerate(rows):
        y=70+n*77 if mobile else 107+n*38
        body += rect(12,y-21,w-24,60 if mobile else 31,BLUE,f'class="rowlight" style="--delay:{n*2}s" opacity="0"')
        body += txt(18,y,short(r['name'],32),20 if mobile else 15,WHITE,'font-weight="700"')
        if mobile:
            body += txt(18,y+27,f"{r['language'] or '—'}  /  {r['stars']} stars  /  {r['forks']} forks",14,BLUE)
        else:
            body += txt(434,y,short(r['language'] or '—',17),14,BLUE)+txt(638,y,r['stars'],14)+txt(742,y,r['forks'],14)+txt(835,y,(r['pushed_at'] or '')[:10] or '—',12,MUTED)
    if not rows:
        body += txt(18,70,'No public projects yet.',16,MUTED)
    body += foot(w,h,f'{len(rows)} original public projects','updated '+data['sampled_at'][:10] if not mobile else '',mobile)
    return wrap(body,w,h,'Public repository table','Original public repositories, showing language, stars, forks and last push. '+', '.join(r['name'] for r in rows))


def languages(data, mobile=False):
    rows=data['languages'][:8]
    w,h=(480,83+max(1,len(rows))*63) if mobile else (960,90+max(1,len(rows))*37)
    body=head(w,'du --languages','SOURCE BYTES' if not mobile else '',mobile)
    for n,row in enumerate(rows):
        y=67+n*(63 if mobile else 37)
        pct=row['percentage']
        col=PALETTE[n%len(PALETTE)]
        body += txt(18,y,short(row['name'],20),18 if mobile else 14,WHITE)
        bx,by,bw=(18,y+11,443) if mobile else (177,y-14,638)
        body += rect(bx,by,bw,9 if mobile else 17,SURFACE)
        body += rect(bx,by,round(bw*pct/100,2),9 if mobile else 17,col,'class="meter"')
        body += txt(w-18,y,f'{pct:.1f}%',16 if mobile else 13,col,'text-anchor="end"')
    if not rows:
        body += txt(18,64,'No language data available.',16,MUTED)
    body += foot(w,h,'original repos / excluding forks','top source languages' if not mobile else '',mobile)
    return wrap(body,w,h,'Source language distribution','Public original repository language byte distribution: '+', '.join(f"{r['name']} {r['percentage']:.1f}%" for r in rows))


def events(data, mobile=False):
    rows=data['commits'][:6]
    w,h=(480,89+max(1,len(rows))*70) if mobile else (960,93+max(1,len(rows))*33)
    body=head(w,'git log -6 --public','RECENT COMMITS' if not mobile else '',mobile)
    for n,row in enumerate(rows):
        y=68+n*(70 if mobile else 33)
        ts=row['created_at'].replace('T',' ')[:16]
        name=row['repo'].split('/')[-1]
        body += rect(12,y-20,w-24,57 if mobile else 28,BLUE,f'class="rowlight" style="--delay:{n*1.5}s" opacity="0"')
        if mobile:
            body += txt(18,y,ts,13,MUTED)+txt(w-18,y,short(row['message'],19),13,BLUE,'text-anchor="end"')
            body += txt(18,y+28,short(name,34),19,WHITE)
        else:
            body += txt(18,y,ts,12,MUTED)+txt(191,y,short(row['message'],24),13,BLUE)+txt(441,y,short(name,42),14)
    if not rows:
        body += txt(18,68,'No commits in public repositories yet.',15,MUTED)
    body += foot(w,h,'public commits / UTC','updated '+data['sampled_at'][:10] if not mobile else '',mobile)
    return wrap(body,w,h,'Recent public commit log','Recent commits in public repositories. '+ '; '.join(f"{r['created_at']}: {r['message']} in {r['repo']}" for r in rows))


def transcript(data):
    parts=['LUCA-1802 / PUBLIC PROFILE', 'Updated '+data['sampled_at'], '', 'Software / automation. Germany.', 'Python, TypeScript, React, Docker, Git, CLI.', '', 'STATISTICS', f"Public repositories: {len(data['repos'])}", f"Stars on original repositories: {sum(r['stars'] for r in data['repos'] if not r['is_fork'])}", f"Followers: {data['profile']['followers']}", '', 'PUBLIC REPOSITORIES']
    parts += [f"{r['name']} | {r['language'] or 'no language'} | {r['stars']} stars | {r['url']}" for r in data['repos']]
    parts += ['', 'LANGUAGE BYTES / ORIGINAL REPOSITORIES'] + [f"{r['name']}: {r['percentage']:.1f}% ({r['bytes']} bytes)" for r in data['languages']]
    parts += ['', 'RECENT PUBLIC COMMITS / UTC'] + [f"{r['created_at']} | {r['message']} | {r['repo']} | {r['url']}" for r in data['commits']]
    parts += ['', 'RECENT PUBLIC EVENTS / UTC'] + [f"{r['created_at']} | {r['message']} | {r['repo']} | {r['url']}" for r in data['events']]
    parts += ['', '30-DAY PUBLIC EVENT SAMPLE / NOT TOTAL CONTRIBUTIONS'] + [f"{r['date']}: {r['count']}" for r in data['activity']]
    return '\n'.join(parts)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=ROOT/'assets/profile-data.json')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'assets')
    args=parser.parse_args()
    data=json.loads(args.data.read_text(encoding='utf-8'))
    if data['schema_version']!=1 or data['login']!='luca-1802':
        raise ValueError('Unexpected profile snapshot identity or schema')
    for row in data['languages']:
        if not 0<=row['percentage']<=100:
            raise ValueError('Invalid language percentage')
    assets={'mark.svg':mark()}
    for name,fn in [('hero',hero),('stats',stats),('repos',repos),('languages',languages),('events',events)]:
        for mobile in (False,True):
            assets[name+('-mobile' if mobile else '')+'.svg']=fn(data,mobile)
    for name,fn in [('ticker',ticker),('boot',boot),('hexdump',hexdump)]:
        for mobile in (False,True):
            assets[name+('-mobile' if mobile else '')+'.svg']=fn(mobile)
    for content in assets.values():
        ET.fromstring(content)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for name,content in assets.items():
        (args.output_dir/name).write_text(content,encoding='utf-8',newline='\n')
    (args.output_dir/'profile.txt').write_text(transcript(data),encoding='utf-8',newline='\n')
    print(f'Rendered {len(assets)} SVG assets and an accessible text view.')


if __name__=='__main__':
    main()
