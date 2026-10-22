"""Rasi-only PDF layout, editable text metadata, assets and optional links."""
from __future__ import annotations
import base64, hashlib, json, re
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import fitz
from PIL import Image, ImageOps
import text_engine as text

ROOT=Path(__file__).resolve().parent
ASSET=ROOT/'asset'
PAGE=fitz.Rect(0,0,612,792)
CONTENT=fitz.Rect(72,72,540,690)
COVER_RECT=fitz.Rect(31,31,581,761)
MAX_BYTES=600_000
NAMES=('மேஷம்','ரிஷபம்','மிதுனம்','கடகம்','சிம்மம்','கன்னி','துலாம்','விருச்சிகம்','தனுசு','மகரம்','கும்பம்','மீனம்')
ALIASES={'மேசம்':0,'இடபம்':1,'ரிசபம்':1,'மிதுன':2,'விருச்சகம்':7,'தனுசு ராசி':8}
BODY=ASSET/'font/Uni Ila.Sundaram-01.ttf'
SUB=ASSET/'font/Uni Ila.Sundaram-06.ttf'
DEFAULT_ASSETS={'cover':ASSET/'Weekly_Rasipalan_pdf_cover_new design_2026.jpg','back':ASSET/'back cover page.jpg',
                'banner1':ASSET/'1.jpg','banner2':ASSET/'2.jpg','footer':ASSET/'footer.png',
                **{f'zodiac{i+1}':ASSET/f'zodiac/{i+1}.png' for i in range(12)}}
DEFAULT_LINKS={'banner':'https://bit.ly/3XZ93SP_lifehoroscope_PDF',
               'app':'https://play.google.com/store/apps/details?id=com.coderays.tamilcalendar&referrer=utm_source%3DShare%26utm_medium%3DInstall%26utm_campaign%3Drk2026',
               'contact':'https://omtamilcalendar.com/apps/webview/business_ads/omastro.html','mail':'mailto:omastro@omtamilcalendar.com'}

@dataclass
class Result:
    data:bytes
    placements:list
    labels:list
    rasis:list
    @property
    def page_count(self):return len(self.labels)

def valid_link(value):
    value=str(value or '').strip()
    if not value:return ''
    parsed=urlsplit(value)
    if parsed.scheme not in ('https','http','mailto') or (parsed.scheme!='mailto' and not parsed.netloc) or (parsed.scheme=='mailto' and '@' not in parsed.path):
        raise ValueError('Links must be complete https://, http:// or mailto: addresses.')
    if any(ord(c)<32 for c in value):raise ValueError('A link contains control characters.')
    return value

def rasi_index(value):
    value=text.normalize_article_text(value).strip().rstrip(':：').strip()
    return NAMES.index(value) if value in NAMES else ALIASES.get(value)

def docx_text(data):
    with ZipFile(BytesIO(data)) as doc:
        if doc.getinfo('word/document.xml').file_size>8_000_000:raise ValueError('The Word document is too large.')
        node=ET.fromstring(doc.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    return '\n'.join(''.join(p.itertext()).strip() for p in node.findall('.//w:p',ns))

def parse_plain(value):
    blocks=[]
    for line in value.splitlines():
        line=line.strip()
        if not line:continue
        kind='heading' if rasi_index(line) is not None else 'subheading' if line.endswith((':','：')) and len(line)<100 else 'body'
        match=re.match(r'^(\d+)\.\s+(.+)$',line)
        block={'type':kind,'text':line}
        if match:block.update(type='number',number=int(match[1]),text=match[2])
        elif line.startswith(('• ','- ')):block.update(type='bullet',text=line[2:])
        blocks.append(block)
    return blocks

def clean(raw):
    result=text.clean_blocks(raw)
    for block in result:
        source=raw[block['source_index']].get('runs') or []
        for run,original in zip(block['runs'],source):
            if original.get('href'):run['href']=valid_link(original['href'])
        text.validate_text(block['text'],BODY)
    return result

def css():
    return '''@font-face{font-family:Body;src:url("asset/font/Uni Ila.Sundaram-01.ttf");}
@font-face{font-family:Sub;src:url("asset/font/Uni Ila.Sundaram-06.ttf");}
@font-face{font-family:Bold;src:url("asset/body-bold.ttf");}
body{font-family:Body;font-size:21.96pt;color:#000;margin:0} p{margin:0;padding:0}
b{font-family:Bold;font-weight:normal} a{color:#0000ff;text-decoration:underline}'''

def story_for(block,options,role='body'):
    size=block.get('font_size') or options.get('font_size',21.96)
    leading=size*options.get('line_height',1.25)
    align=block.get('align','justify')
    if role in ('subheading','lucky') and align=='justify':align='left'
    color=block.get('color') or {'body':'#000000','subheading':'#0000ff','lucky':'#00b050','star':'#948a54','rasi':'#92d050','subtitle':'#ff0000','cover':'#ffffff'}.get(role,'#000000')
    if role in ('rasi','subtitle','cover'):align='center'
    parts=[]
    for run in block['runs']:
        value=escape(run['text']).replace('\n','<br>')
        if run.get('bold'):value=f'<b>{value}</b>'
        if run.get('color'):value=f'<span style="color:{run["color"]}">{value}</span>'
        if run.get('href') and options.get('links_enabled',True):value=f'<a href="{escape(run["href"],quote=True)}">{value}</a>'
        parts.append(value)
    family='Sub' if options.get('heading_font','01')=='06' and role in ('subheading','rasi') else 'Body'
    style=f'font-family:{family};font-size:{size}pt;line-height:{leading}pt;text-align:{align};color:{color}'
    return fitz.Story(f'<p style="{style}">{"".join(parts)}</p>',user_css=css(),archive=fitz.Archive(str(ROOT))),size,leading,align,color

def draw_block(page,story,options):
    anchors=[]
    story.element_positions(lambda p:anchors.append((p.href,fitz.Rect(p.rect))) if p.href and p.open_close&1 else None)
    text.draw_story(page,story)
    if options.get('links_enabled',True):
        for href,rect in anchors:
            rect=rect & PAGE
            if not rect.is_empty:page.insert_link({'kind':fitz.LINK_URI,'from':rect,'uri':valid_link(href)})

def link(page,rect,uri,options):
    if uri and options.get('links_enabled',True):page.insert_link({'kind':fitz.LINK_URI,'from':rect,'uri':valid_link(uri)})

@lru_cache(maxsize=64)
def prepare(data,width,height,zoom=1.,pan_x=0.,pan_y=0.,quality=82,fit='contain'):
    if len(data)>25*1024*1024:raise ValueError('Each image must be smaller than 25 MiB.')
    with Image.open(BytesIO(data)) as image:
        if image.width*image.height>40_000_000:raise ValueError('Resize images larger than 40 megapixels before uploading.')
        image=ImageOps.exif_transpose(image).convert('RGBA')
    scale=(min(width/image.width,height/image.height) if fit=='contain' else max(width/image.width,height/image.height))*zoom
    image=image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(width,height),'white')
    x=round((width-image.width)*(pan_x+1)/2);y=round((height-image.height)*(pan_y+1)/2)
    canvas.paste(image,(x,y),image)
    out=BytesIO();canvas.convert('RGB').save(out,format='JPEG',quality=quality,optimize=True)
    return out.getvalue()

def image(page,key,rect,overrides,crops,quality=82,max_side=1100):
    data=overrides.get(key)
    if data is None:data=DEFAULT_ASSETS[key].read_bytes()
    crop=crops.get(key,{})
    if not crop.get('show',True):return False
    scale=min(4.2 if key=='footer' else 2.,max_side/max(rect.width,rect.height))
    stream=prepare(data,max(1,round(rect.width*scale)),max(1,round(rect.height*scale)),crop.get('zoom',1.),crop.get('pan_x',0.),crop.get('pan_y',0.),quality,crop.get('fit','contain'))
    page.insert_image(rect,stream=stream,keep_proportion=False)
    return True

def frame(doc,labels,label,options,overrides,crops,links):
    page=doc.new_page(width=612,height=792);labels.append(label)
    for inset,width in ((24,1.2),(27,.5),(30,1.2)):
        page.draw_rect(fitz.Rect(inset,inset,612-inset,792-inset),color=(.22,.22,.22),width=width)
    if image(page,'footer',fitz.Rect(72,696,110,734),overrides,crops,max_side=160):
        page.insert_text((72,744),'Om Tamil Calendar (Android App)',fontname='Times-Roman',fontsize=8,color=(0,0,1))
        page.insert_text((72,753),'Click Here To Download',fontname='Times-Roman',fontsize=8,color=(0,0,1))
        link(page,fitz.Rect(70,695,210,757),links.get('app',''),options)
    if options.get('page_numbers',False):page.insert_text((515,750),str(len(doc)),fontsize=9,color=(.35,.35,.35))
    return page


@lru_cache(maxsize=2)
def unicode_cmap(path):
    # The supplied font's GSUB Tamil ligatures have legacy glyph names. MuPDF
    # renders them correctly but guesses Latin Unicode values for extraction.
    # Recover each ligature's Unicode sequence from the actual font GSUB table.
    from fontTools.ttLib import TTFont
    with TTFont(path) as font:
        mapping={}
        for code,glyph in font.getBestCmap().items():
            if glyph not in mapping or 0xB80<=code<=0xBFF or 32<=code<=126:
                mapping[glyph]=chr(code)
        if 'GSUB' in font:
            for _ in range(8):
                changed=False
                for lookup in font['GSUB'].table.LookupList.Lookup:
                    for sub in lookup.SubTable:
                        for first,ligatures in getattr(sub,'ligatures',{}).items():
                            for ligature in ligatures:
                                parts=[first,*ligature.Component]
                                if not all(part in mapping for part in parts):continue
                                value=''.join(mapping[part]for part in parts)
                                if any('\u0b80'<=c<='\u0bff'for c in value) and mapping.get(ligature.LigGlyph)!=value:
                                    mapping[ligature.LigGlyph]=value;changed=True
                if not changed:break
        entries=[f'<{font.getGlyphID(glyph):04x}> <{value.encode("utf-16-be").hex()}>'for glyph,value in mapping.items()]
    chunks=['/CIDInit /ProcSet findresource begin','12 dict begin','begincmap',
            '/CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def',
            '/CMapName /Rasi-Unicode def','/CMapType 2 def','1 begincodespacerange','<0000> <FFFF>','endcodespacerange']
    for index in range(0,len(entries),100):
        part=entries[index:index+100];chunks += [f'{len(part)} beginbfchar',*part,'endbfchar']
    return ('\n'.join(chunks+['endcmap','CMapName currentdict /CMap defineresource pop','end','end'])+'\n').encode('ascii')

def repair_unicode_maps(doc):
    done=set()
    for page in doc:
        for entry in page.get_fonts(full=True):
            if entry[0] in done:continue
            done.add(entry[0]);name=entry[3]
            if not any(part in name for part in ('Sundaram-01','Sundaram-06','MagazineBold')):continue
            kind,value=doc.xref_get_key(entry[0],'ToUnicode')
            if kind=='xref':doc.update_stream(int(value.split()[0]),unicode_cmap(str(SUB if 'Sundaram-06'in name else BODY)))

def compact(doc):
    repair_unicode_maps(doc)
    doc.subset_fonts();original=doc.tobytes(garbage=4,deflate=True,use_objstms=1)
    if len(original)<MAX_BYTES:return original
    # Rewrite each unique image once, never once per page. This keeps reused
    # footer/zodiac artwork sharp and avoids progressive shared-image blur.
    for max_side,quality in ((900,78),(750,68),(600,55),(480,42),(360,28)):
        with fitz.open(stream=original,filetype='pdf') as candidate:
            xrefs={im[0] for page in candidate for im in page.get_images()}
            for xref in xrefs:
                pix=fitz.Pixmap(candidate,xref)
                if pix.width<=240 and pix.height<=240:continue
                if pix.colorspace is None:continue
                im=Image.frombytes('RGB' if pix.n==3 else 'RGBA' if pix.n==4 else 'L',(pix.width,pix.height),pix.samples).convert('RGB')
                im.thumbnail((max_side,max_side),Image.Resampling.LANCZOS);out=BytesIO();im.save(out,format='JPEG',quality=quality,optimize=True)
                candidate[0].replace_image(xref,stream=out.getvalue())
            data=candidate.tobytes(garbage=4,deflate=True,use_objstms=1)
            if len(data)<MAX_BYTES:return data
    raise ValueError('This issue cannot fit below 600 KB. Use simpler images, fewer pages, or shorten the text.')

def generate(raw,options=None,overrides=None,crops=None,links=None):
    options=options or {};overrides=overrides or {};crops=crops or {};links=links or {}
    blocks=clean(raw);text.ensure_bold_font(BODY)
    starts=[(i,rasi_index(b['text']))for i,b in enumerate(blocks)if rasi_index(b['text']) is not None]
    if not starts:raise ValueError('Paste at least one rasi heading such as மேஷம், followed by its article.')
    indices=[s[1] for s in starts]
    if len(set(indices))!=len(indices):raise ValueError('A rasi heading appears more than once. Keep one section for each rasi.')
    labels=[];placements=[];subtitles=options.get('subtitles',[])
    # A parenthesized line immediately after a zodiac is its pasted subtitle,
    # not a body paragraph. It replaces the sidebar fallback without altering
    # source indices, so it stays editable and cannot trigger the banner.
    pasted_subtitles={}
    for position,_ in starts:
        if position+1<len(blocks):
            value=blocks[position+1]['text'].strip()
            if value.startswith('(') and value.endswith(')'):
                pasted_subtitles[position]=position+1
    subtitle_indices=set(pasted_subtitles.values())
    with fitz.open() as doc:
        cover=frame(doc,labels,'Front cover',options,overrides,crops,links)
        if options.get('cover',True):
            image(cover,'cover',COVER_RECT,overrides,crops)
            prefix=blocks[:starts[0][0]]
            date_block=next((b for b in reversed(prefix) if re.search(r'\d',b['text'])),None)
            date_value=options.get('issue_label') or (date_block['text']if date_block else '')
            if date_value:
                block=dict(date_block or {'source_index':-1},text=date_value,runs=date_block['runs'] if date_block and not options.get('issue_label') else [{'text':date_value,'bold':False}],font_size=(date_block or {}).get('font_size') or options.get('cover_date_size',18),align='center')
                s,size,leading,align,color=story_for(block,options,'cover');more,filled=s.place(fitz.Rect(46,686,566,730))
                if more:raise ValueError('The cover date is too long. Shorten it or reduce Cover date size.')
                draw_block(cover,s,options)
                if date_block and not options.get('issue_label'):
                    placements.append({'page':0,'source_index':date_block['source_index'],'type':'body','rect':[46,686,566,730],'font_size':size,'line_height':leading,'align':'center','color':'#ffffff'})
        else:
            doc.delete_page(0);labels.clear()
        page=None;y=72.;active_rasi=None;banner_pending=None;body_seen=False;star_mode=False
        def new_page():return frame(doc,labels,f'Page {len(doc)+1}',options,overrides,crops,links)
        def add_banner(index):
            nonlocal page,y
            choice=options.get('banners',{}).get(str(index),1 if index%2==0 else 2)
            if not choice or not crops.get(f'banner{choice}',{}).get('show',True):return
            height=121.3
            if y+height+12>CONTENT.y1:page=new_page();y=CONTENT.y0
            rect=fitz.Rect(154.35,y,457.65,y+height)
            if image(page,f'banner{choice}',rect,overrides,crops):link(page,rect,links.get('banner',''),options);y+=height+14
        for index,block in enumerate(blocks[starts[0][0]:],start=starts[0][0]):
            rasi=rasi_index(block['text'])
            if rasi is not None:
                if banner_pending is not None:add_banner(banner_pending)
                active_rasi=rasi;banner_pending=rasi;body_seen=False;star_mode=False
                if page is None:page=new_page();y=CONTENT.y0
                header_height=182 if index in pasted_subtitles or (rasi<len(subtitles) and subtitles[rasi]) else 151
                if y+header_height+56>CONTENT.y1:page=new_page();y=CONTENT.y0
                image(page,f'zodiac{rasi+1}',fitz.Rect(251.5,y,360.5,y+109),overrides,crops,max_side=240);y+=112
                role='rasi';block=dict(block,align='center')
            elif index in subtitle_indices:
                role='subtitle';block=dict(block,align='center')
            else:
                if banner_pending is not None and body_seen:add_banner(banner_pending);banner_pending=None
                if block['text'].startswith('அதிர்ஷ்டம் அளிப்பவை'):star_mode=True
                if block['text'].startswith('அதிர்ஷ்டம் அளிப்பவை'):role='lucky'
                elif block['type']in('heading','subheading')or(len(block['text'])<100 and block['text'].endswith((':','：'))):role='subheading'
                elif block['text'].startswith(('அதிர்ஷ்ட நிறம்','அதிர்ஷ்ட திசை','அதிர்ஷ்ட எண்')):role='lucky'
                elif star_mode:role='star'
                else:role='body'
            story,size,leading,align,color=story_for(block,options,role)
            left=94 if block['type']in('bullet','number') else CONTENT.x0
            _,bounds=story.place(fitz.Rect(left,0,CONTENT.x1,100000));height=bounds[3];story.reset()
            if page is None:page=new_page();y=CONTENT.y0
            keep=height+(2*leading+8 if role=='subheading' else 0)
            if role=='lucky' and block['text'].startswith('அதிர்ஷ்டம் அளிப்பவை'):
                keep += sum((b.get('font_size') or options.get('font_size',21.96))*options.get('line_height',1.25)+2 for b in blocks[index+1:index+4] if b['text'].startswith(('அதிர்ஷ்ட நிறம்','அதிர்ஷ்ட திசை','அதிர்ஷ்ட எண்')))
            if role in ('subheading','lucky') and keep<=CONTENT.height and y+keep>CONTENT.y1:page=new_page();y=CONTENT.y0
            elif role=='body' and height>CONTENT.y1-y and CONTENT.y1-y<2*leading:page=new_page();y=CONTENT.y0
            first=True
            while True:
                more,filled=story.place(fitz.Rect(left,y,CONTENT.x1,CONTENT.y1))
                if filled[3]<=y+.01:
                    if y<=CONTENT.y0+.01:raise ValueError('A text block cannot fit. Reduce its font size or break long words.')
                    page=new_page();y=CONTENT.y0;continue
                if first and block['type']in('bullet','number'):
                    marker='•'if block['type']=='bullet'else f'{block["number"]}.'
                    page.insert_font(fontname='ListNumber',fontfile=str(BODY));page.insert_text((72,y+size),marker,fontname='ListNumber',fontsize=size)
                draw_block(page,story,options)
                placements.append({'page':len(doc)-1,'source_index':block['source_index'],'type':block['type'],
                                   'rect':[left,y,CONTENT.x1,min(CONTENT.y1,filled[3])],'font_size':size,'line_height':leading,'align':align,'color':color})
                first=False;y=filled[3]
                if not more:break
                page=new_page();y=CONTENT.y0
            y+=2 if role=='lucky' else 10 if role in('subheading','rasi')else 12
            if rasi is not None and index not in pasted_subtitles and rasi<len(subtitles) and subtitles[rasi]:
                value=subtitles[rasi];sb={'text':value,'runs':[{'text':value,'bold':False}], 'align':'center'}
                st,_,_,_,_=story_for(sb,options,'subtitle');more,filled=st.place(fitz.Rect(72,y,540,min(y+80,690)))
                if more:raise ValueError(f'The subtitle for {NAMES[rasi]} is too long.')
                draw_block(page,st,options);y=filled[3]+12
            if rasi is None and role=='body':body_seen=True
        if banner_pending is not None:add_banner(banner_pending)
        if options.get('back',True):
            back=frame(doc,labels,'Back cover',options,overrides,crops,links)
            if image(back,'back',COVER_RECT,overrides,crops):
                for rect,key in [(fitz.Rect(136,640,270,732),'app'),(fitz.Rect(423,637,559,690),'contact'),(fitz.Rect(425,698,574,734),'mail')]:link(back,rect,links.get(key,''),options)
        doc.set_metadata({'title':'Weekly Rasi Palan','creator':'Rasi PDF Generator — local Tamil shaping'})
        return Result(compact(doc),placements,labels,[NAMES[i]for i in indices])

def preview(result,scale=1.):
    with fitz.open(stream=result.data,filetype='pdf') as doc:
        return [{'image':base64.b64encode(page.get_pixmap(matrix=fitz.Matrix(scale,scale)).tobytes('png')).decode(),
                 'label':result.labels[index],'placements':[p for p in result.placements if p['page']==index]}
                for index,page in enumerate(doc)]
