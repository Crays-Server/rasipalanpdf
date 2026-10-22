"""Run: python -m streamlit run app.py"""
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
import base64,hashlib,json
import streamlit as st
import streamlit.components.v1 as components
import engine

ROOT=Path(__file__).resolve().parent

def load_article(value):
    st.session_state['article']=engine.parse_plain(value)
    st.session_state['revision']=str(uuid4())
    st.session_state['source_token']=str(uuid4())
    st.session_state['force_refresh']=True

def main():
    st.set_page_config(page_title='Rasi PDF Generator',page_icon='♈',layout='wide')
    st.title('Weekly Rasi PDF Generator')
    st.caption('Tamil rasi articles · 12 zodiac images · editable PDF preview · optional links · under 600 KB')
    if not engine.text.complete_font(engine.BODY):
        st.error('The supplied complete Sundaram-01 font is missing or invalid.');return
    st.session_state.setdefault('article',[]);st.session_state.setdefault('revision','initial')
    st.session_state.setdefault('source_token',str(uuid4()))
    auto=st.toggle('Auto preview refresh',value=True,key='auto_preview')
    with st.expander('Load article from Word or text'):
        st.caption('Or paste directly into the Article editor below. Loading a file replaces the current article.')
        uploaded=st.file_uploader('Raw article (.docx or .txt)',type=['docx','txt'],key='raw_upload')
        col1,col2=st.columns(2)
        if col1.button('Load uploaded article',disabled=uploaded is None):
            try:
                value=engine.docx_text(uploaded.getvalue()) if uploaded.name.lower().endswith('.docx') else uploaded.getvalue().decode('utf-8-sig')
                load_article(value);st.rerun()
            except Exception as error:st.error(str(error))
        if col2.button('Load supplied Raw.docx',disabled=not(ROOT/'Raw.docx').exists()):
            try:load_article(engine.docx_text((ROOT/'Raw.docx').read_bytes()));st.rerun()
            except Exception as error:st.error(str(error))
    overrides=st.session_state.setdefault('asset_overrides',{})
    crops=st.session_state.setdefault('asset_crops',{})
    versions=st.session_state.setdefault('asset_versions',{})
    with st.sidebar:
        st.header('Rasi layout')
        body_size=st.number_input('Default text size (pt)',8.,60.,21.96,.5)
        line_height=st.slider('Line spacing',1.05,1.8,1.25,.05)
        heading_font=st.selectbox('Heading font',['01','06'],format_func=lambda n:f'Sundaram-{n}')
        cover=st.checkbox('Include front cover',value=True)
        back=st.checkbox('Include back cover',value=True)
        page_numbers=st.checkbox('Show page numbers',value=False)
        issue_label=st.text_input('Cover date override (optional)',help='Leave empty to use the date paragraph before the first rasi in the pasted text.')
        cover_date_size=st.slider('Cover date size',10,30,18)
        st.header('Images and movement')
        labels={'cover':'Front cover','back':'Back cover','banner1':'Banner 1','banner2':'Banner 2','footer':'Footer logo',**{f'zodiac{i+1}':f'{i+1}. {name}'for i,name in enumerate(engine.NAMES)}}
        selected=st.selectbox('Choose image',list(labels),format_func=labels.get)
        if st.button('Use supplied image',key='reset_asset'):
            overrides.pop(selected,None);versions[selected]=versions.get(selected,0)+1;st.rerun()
        custom=st.file_uploader('Replace selected image (optional)',type=['png','jpg','jpeg','webp'],key=f'image_{selected}_{versions.get(selected,0)}')
        if custom is not None:
            if custom.size>25*1024*1024:st.error('Each image must be smaller than 25 MiB.')
            else:overrides[selected]=custom.getvalue()
        if selected in overrides:st.caption('Using your uploaded image for this slot.')
        current=crops.setdefault(selected,{'zoom':1.,'pan_x':0.,'pan_y':0.,'show':True,'fit':'contain'})
        with st.expander('Selected image movement / visibility',expanded=True):
            crops[selected]={
                'show':st.checkbox('Show selected image',value=current.get('show',True),key=f'show_{selected}'),
                'fit':st.selectbox('Image fit',['contain','cover'],index=0 if current.get('fit','contain')=='contain'else 1,key=f'fit_{selected}'),
                'zoom':st.slider('Zoom',1.,3.,current.get('zoom',1.),.05,key=f'zoom_{selected}'),
                'pan_x':st.slider('Horizontal movement',-1.,1.,current.get('pan_x',0.),.05,key=f'x_{selected}'),
                'pan_y':st.slider('Vertical movement',-1.,1.,current.get('pan_y',0.),.05,key=f'y_{selected}')}
        with st.expander('Banner choice for each rasi'):
            banners={str(i):st.selectbox(name,[0,1,2],index=1 if i%2==0 else 2,format_func=lambda n:'No banner'if n==0 else f'Banner {n}',key=f'banner_rasi_{i}') for i,name in enumerate(engine.NAMES)}
        with st.expander('Zodiac subtitles (editable)'):
            default=json.loads((engine.ASSET/'zodiac_subtitles.json').read_text(encoding='utf-8'))
            st.caption('Fallback subtitles from the reference PDF. A parenthesized line pasted directly after a rasi heading replaces its fallback and prints once in red. Clear any fallback you do not need.')
            subtitles=[st.text_input(name,value=default[i] if i<len(default)else '',key=f'subtitle_{i}')for i,name in enumerate(engine.NAMES)]
        with st.expander('Optional links',expanded=False):
            links_enabled=st.checkbox('Enable clickable PDF links',value=True)
            st.caption('Clear a URL to omit that link. APPLY LINK in the editor adds a link to selected text.')
            links={key:st.text_input(label,value=engine.DEFAULT_LINKS[key],key=f'url_{key}')for key,label in [('banner','Banner link'),('app','Footer / Android app link'),('contact','Back-cover contact link'),('mail','Back-cover email link')]}
    options={'font_size':body_size,'line_height':line_height,'heading_font':heading_font,'cover':cover,'back':back,'page_numbers':page_numbers,
             'issue_label':issue_label,'cover_date_size':cover_date_size,'banners':banners,'subtitles':subtitles,'links_enabled':links_enabled}
    article=st.session_state['article'];revision=st.session_state['revision']
    signature=('rasi-v3-pasted-subtitle',article,options,crops,links,[(key,hashlib.sha256(value).hexdigest())for key,value in sorted(overrides.items())])
    fingerprint=hashlib.sha256(repr(signature).encode()).hexdigest()
    force=st.session_state.pop('force_refresh',False)
    if (auto or force) and fingerprint!=st.session_state.get('preview_fingerprint'):
        try:
            for value in links.values():engine.valid_link(value)
            result=engine.generate(article,options,overrides,crops,links)if article else None
            st.session_state['result']=result
            st.session_state['pages']=engine.preview(result)if result else []
            st.session_state['error']=''
        except Exception as error:
            st.session_state['result']=None;st.session_state['pages']=[];st.session_state['error']=str(error)
        st.session_state['preview_fingerprint']=fingerprint
    fresh=fingerprint==st.session_state.get('preview_fingerprint')
    if fresh:st.session_state['preview_revision']=revision
    if st.session_state.get('generated_for')!=fingerprint:st.session_state.pop('download_data',None)
    component=components.declare_component('rasi_editor',path=str(ROOT/'editor'))
    value=component(font=base64.b64encode(engine.BODY.read_bytes()).decode(),initial=article,initial_revision=revision,
                    initial_token=st.session_state['source_token'],preview=st.session_state.get('pages',[]),preview_revision=st.session_state.get('preview_revision','initial'),
                    preview_error=st.session_state.get('error',''),context=fingerprint,auto_preview=auto,preview_stale=not fresh,key='rasi_editor',default=None)
    if value and value.get('initial_token')==st.session_state['source_token']:
        incoming=value.get('blocks',[]);new_revision=value.get('revision',revision)
        if repr(incoming)!=repr(article)or new_revision!=revision:
            st.session_state['article']=incoming;st.session_state['revision']=new_revision;st.rerun()
        refresh=value.get('refresh_request')
        if refresh and refresh!=st.session_state.get('handled_refresh'):
            st.session_state['handled_refresh']=refresh;st.session_state['force_refresh']=True;st.rerun()
        request=value.get('request')
        if request and request!=st.session_state.get('handled_generate'):
            if not fresh:st.session_state['force_refresh']=True;st.rerun()
            st.session_state['handled_generate']=request
            result=st.session_state.get('result')
            if result is None:st.error(st.session_state.get('error')or'Paste a rasi article before generating.')
            else:
                stamp=datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d_%H%M%S')
                filename=f'weekly_rasi_{stamp}_{uuid4().hex[:6]}.pdf'
                (ROOT/'output').mkdir(exist_ok=True);(ROOT/'output'/filename).write_bytes(result.data)
                st.session_state.update(download_data=result.data,download_name=filename,generated_for=fingerprint)
    result=st.session_state.get('result')
    if result is not None and fresh:
        st.caption(f'{result.page_count} pages · {len(result.rasis)}/12 rasis detected · {len(result.data)/1000:.1f} KB / 600 KB')
    if 'download_data'in st.session_state:
        st.download_button('DOWNLOAD PDF',data=st.session_state['download_data'],file_name=st.session_state['download_name'],mime='application/pdf',use_container_width=True)
    st.caption('Rasi-only generator. Source text is preserved; page count can change with edits and font sizes. No AI API or key is required.')

if __name__=='__main__':main()
