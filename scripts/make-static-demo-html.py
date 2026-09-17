from pathlib import Path
import base64, re
root=Path('demo-dist')
index=root/'index.html'
s=index.read_text()
for src in re.findall(r'<script[^>]+src="([^"]+)"[^>]*></script>',s):
    path=root/src.lstrip('./'); content=path.read_text();
    for asset in path.parent.glob('*'):
        if asset.suffix.lower() in {'.png','.jpg','.jpeg','.woff2','.woff'}:
            token='data:' + ({'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.woff2':'font/woff2','.woff':'font/woff'}.get(asset.suffix.lower(),'application/octet-stream')) + ';base64,' + base64.b64encode(asset.read_bytes()).decode()
            content=content.replace(f'"{asset.name}"',f'"{token}"')
    s=s.replace(f'<script type="module" crossorigin src="{src}"></script>',f'<script type="module">{content}</script>')
for href in re.findall(r'<link[^>]+href="([^"]+\.css)"[^>]*>',s):
    path=root/href.lstrip('./'); css=path.read_text()
    for asset in path.parent.glob('*'):
        if asset.suffix.lower() in {'.png','.jpg','.jpeg','.woff2','.woff'}:
            token='data:' + ({'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.woff2':'font/woff2','.woff':'font/woff'}.get(asset.suffix.lower(),'application/octet-stream')) + ';base64,' + base64.b64encode(asset.read_bytes()).decode()
            css=css.replace(f'url({asset.name})',f'url({token})').replace(f'url("{asset.name}")',f'url("{token}")')
    s=s.replace(f'<link rel="stylesheet" crossorigin href="{href}">',f'<style>{css}</style>')
Path('demo-static.html').write_text(s)
print('wrote demo-static.html',len(s),'bytes')
