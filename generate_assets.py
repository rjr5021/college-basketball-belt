#!/usr/bin/env python3
"""Generate the site's static images: favicon, touch icon and the default
Open Graph card, in the ink/brass medallion style with the orange ball (same
art as the @CollegeBBBelt avatar). Run once; outputs are committed."""
from PIL import Image, ImageDraw, ImageFont
import math, os
OUT="."
INK=(31,24,18); BRASS=(214,176,106); BRASS_D=(160,124,64); CREAM=(239,230,214); ORANGE=(222,118,44)
SERIF="/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
BODY="/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
MONO="/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
def F(p,s): return ImageFont.truetype(p,s)

def octagon(cx,cy,r):
    return [(cx+r*math.cos(math.radians(22.5+45*i)), cy+r*math.sin(math.radians(22.5+45*i))) for i in range(8)]

def tall_oct(cx,cy,w,h,c):
    # octagon with chamfer c, width w, height h
    x0,x1,y0,y1=cx-w/2,cx+w/2,cy-h/2,cy+h/2
    return [(x0+c,y0),(x1-c,y0),(x1,y0+c),(x1,y1-c),(x1-c,y1),(x0+c,y1),(x0,y1-c),(x0,y0+c)]

def medallion(d, cx, cy, s, emblem=None):
    """s = overall scale (medallion height). Matches CFB mark: strap, side plates, octagon ring."""
    W=s*0.78; H=s; c=s*0.22; ring=s*0.085
    # strap
    sh=s*0.30
    d.rectangle([cx-s*1.02, cy-sh/2, cx+s*1.02, cy+sh/2], fill=BRASS)
    # side plates
    for sgn in (-1,1):
        px=cx+sgn*s*0.74; pw=s*0.30; ph=s*0.50
        d.rectangle([px-pw/2, cy-ph/2, px+pw/2, cy+ph/2], fill=BRASS)
        d.rectangle([px-pw/2, cy-ph/2, px+pw/2, cy+ph/2], outline=INK, width=max(2,int(s*0.035)))
        lx=px - sgn*pw*0.15
        d.line([(lx, cy-ph/2), (lx, cy+ph/2)], fill=INK, width=max(2,int(s*0.03)))
    # center octagon: ink gap, brass ring, ink center
    d.polygon(tall_oct(cx,cy,W+ring*1.2,H+ring*1.2,c+ring*0.5), fill=INK)
    d.polygon(tall_oct(cx,cy,W,H,c), fill=BRASS)
    d.polygon(tall_oct(cx,cy,W-2*ring,H-2*ring,c-ring*0.41), fill=INK)
    if emblem=="ball":
        r=s*0.19
        d.ellipse([cx-r,cy-r,cx+r,cy+r], fill=ORANGE)
        lw=max(2,int(s*0.022))
        d.line([(cx-r,cy),(cx+r,cy)], fill=INK, width=lw)
        d.line([(cx,cy-r),(cx,cy+r)], fill=INK, width=lw)
        # curved seams
        k=r*0.55
        d.arc([cx-r-k*1.6, cy-r, cx-r+k*0.9, cy+r], -70, 70, fill=INK, width=lw)
        d.arc([cx+r-k*0.9, cy-r, cx+r+k*1.6, cy+r], 110, 250, fill=INK, width=lw)
    elif emblem=="star":
        r=s*0.21; ri=r*0.42
        pts=[]
        for i in range(10):
            rr=r if i%2==0 else ri
            a=math.radians(-90+36*i)
            pts.append((cx+rr*math.cos(a), cy+rr*math.sin(a)+s*0.01))
        d.polygon(pts, fill=BRASS)

def avatar(name, emblem, size=1000, ss=3):
    S=size*ss
    img=Image.new("RGB",(S,S),INK); d=ImageDraw.Draw(img)
    medallion(d, S/2, S/2, S*0.42, emblem)
    img=img.resize((size,size),Image.LANCZOS)
    img.save(f"{OUT}/{name}", "PNG")

def tracked(d,xy,t,f,fill,tr):
    x,y=xy
    for ch in t:
        d.text((x,y),ch,font=f,fill=fill); x+=d.textlength(ch,font=f)+tr

def banner(name, eyebrow, word, tag, emblem, ss=2):
    Wd,Ht=1500*ss,500*ss
    img=Image.new("RGB",(Wd,Ht),INK); d=ImageDraw.Draw(img)
    P=90*ss
    medallion(d, P+70*ss, 95*ss, 52*ss, emblem)
    tracked(d,(P,150*ss),eyebrow,F(MONO,24*ss),BRASS,4*ss)
    wf=F(SERIF,78*ss)
    while d.textlength(word,font=wf)>Wd-2*P: wf=F(SERIF,wf.size-2*ss)
    d.text((P,188*ss),word,font=wf,fill=CREAM)
    d.text((P,290*ss),tag,font=F(BODY,32*ss),fill=CREAM)
    img=img.resize((1500,500),Image.LANCZOS)
    img.save(f"{OUT}/{name}","PNG")



def og_card(name="og.png", ss=2):
    Wd,Ht=1200*ss,630*ss
    img=Image.new("RGB",(Wd,Ht),INK); d=ImageDraw.Draw(img)
    P=80*ss
    medallion(d, P+80*ss, 130*ss, 60*ss, "ball")
    tracked(d,(P,215*ss),"LINEAL CHAMPIONSHIP · MEN'S COLLEGE HOOPS",F(MONO,24*ss),BRASS,4*ss)
    d.text((P,258*ss),"COLLEGE BASKETBALL BELT",font=F(SERIF,76*ss),fill=CREAM)
    d.text((P,400*ss),"Beat the champ. Take the belt.",font=F(BODY,40*ss),fill=CREAM)
    d.text((P,520*ss),"collegebasketballbelt.com",font=F(MONO,26*ss),fill=BRASS)
    img.resize((1200,630),Image.LANCZOS).save(f"{OUT}/{name}","PNG")


def icon(name, size, ss=4):
    S=size*ss
    img=Image.new("RGB",(S,S),INK); d=ImageDraw.Draw(img)
    medallion(d, S/2, S/2, S*(0.40 if size>=64 else 0.46), "ball")
    img.resize((size,size),Image.LANCZOS).save(f"{OUT}/{name}","PNG")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    icon("favicon.png", 64)
    icon("apple-touch-icon.png", 180)
    icon("icon-512.png", 512)
    og_card()
    print("wrote", sorted(os.listdir(OUT)))
