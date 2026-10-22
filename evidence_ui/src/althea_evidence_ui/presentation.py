"""Local visual language and escaped, presentation-only markup."""
from html import escape


STYLES = """
<style>
:root { --althea-ink:#202b26; --althea-muted:#6b756e; --althea-line:#e2e7e1; --althea-green:#345b46; }
.stApp { background:#f8f9f5; color:var(--althea-ink); }
[data-testid="stHeader"] { background:rgba(248,249,245,.94); }
[data-testid="stToolbar"] { visibility:hidden; }
[data-testid="stMainBlockContainer"] { max-width:1180px; padding:2.8rem 3.2rem 4rem; }
[data-testid="stSidebar"] { background:#eff2ec; border-right:1px solid var(--althea-line); }
[data-testid="stSidebar"] > div:first-child { padding-top:2rem; }
[data-testid="stSidebarUserContent"] { padding-top:1rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:.85rem; }
.brand { display:flex; align-items:center; gap:10px; margin:0 0 2.2rem; color:#253e30; }
.brand-mark { display:grid; place-items:center; width:32px; height:32px; background:#345b46; border-radius:10px; color:white; font:italic 27px Georgia,serif; }
.brand-name { font-size:24px; font-weight:650; letter-spacing:-1px; }
.brand-name small { margin-left:4px; font-size:10px; letter-spacing:1.5px; font-weight:500; color:#6b756e; }
.eyebrow { color:var(--althea-muted); font-size:10px; font-weight:650; letter-spacing:1.8px; text-transform:uppercase; margin:0 0 14px; }
.hero { padding:4px 0 18px; }
.hero h1 { font-size:clamp(28px,3.4vw,42px); line-height:1.15; font-weight:550; letter-spacing:-1.8px; margin:0 0 14px; color:var(--althea-ink); }
.hero p { color:var(--althea-muted); font-size:15px; line-height:1.65; max-width:600px; margin:0; }
.hero.compact { padding:0 0 4px; }
.hero.compact h1 { font-size:28px; letter-spacing:-.9px; margin:0; }
.hero.compact .eyebrow { margin-bottom:8px; }
h1,h2,h3 { color:var(--althea-ink); letter-spacing:-.5px; }
h3 { font-size:21px !important; font-weight:550 !important; }
[data-testid="stWidgetLabel"] p { font-size:12px; font-weight:550; color:#4f5d53; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { background:#fff !important; border-color:#dce3dc !important; border-radius:9px !important; box-shadow:none !important; }
input,textarea { color:var(--althea-ink) !important; }
[data-testid="stForm"] { background:white; border:1px solid var(--althea-line); border-radius:16px; padding:24px; }
[data-testid="stSidebar"] [data-testid="stForm"] { padding:14px; background:#f7f9f4; border-radius:12px; }
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button,[data-testid="stLinkButton"] a,[data-testid="stFormSubmitButton"] button { border-radius:8px; font-size:12px; min-height:40px; font-weight:550; border-color:#d8e0d8; box-shadow:none; }
button[kind="primary"],button[kind="primaryFormSubmit"] { background:#345b46 !important; border-color:#345b46 !important; color:#fff !important; }
button[kind="primary"]:hover,button[kind="primaryFormSubmit"]:hover { background:#274b37 !important; }
button[kind="primary"]:disabled,button[kind="primaryFormSubmit"]:disabled { background:#dfe5de !important; border-color:#dfe5de !important; color:#899389 !important; cursor:not-allowed; }
button:focus-visible,a:focus-visible { outline:2px solid #345b46 !important; outline-offset:3px; }
[data-testid="stFileUploader"] section { background:#f8faf6; border:1px dashed #cbd7cc; border-radius:12px; padding:28px 18px; }
[data-testid="stFileUploader"] section small { color:#6b756e; }
[data-testid="stAlert"] { border-radius:10px; padding:0; border:none; }
[data-testid="stAlertContainer"] { padding:12px 16px !important; border-radius:10px !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]),[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { background:#eef3ed !important; color:#425647 !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { background:#faf3e4 !important; color:#75613c !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { background:#fbece8 !important; color:#914b3c !important; }
[data-testid="stAlert"] p { font-size:12px; line-height:1.6; }
[data-testid="stAlert"] svg { width:17px; }
[data-testid="stCaptionContainer"] p { color:var(--althea-muted); font-size:12px; line-height:1.65; }
[data-testid="stTabs"] [role="tablist"] { gap:26px; border-bottom:1px solid var(--althea-line); margin:8px 0 18px; }
[data-testid="stTabs"] [role="tab"] { padding:12px 0; color:#778178; font-weight:500; font-size:13px; }
[data-testid="stTabs"] [aria-selected="true"] { color:#294c36; }
[data-baseweb="tab-highlight"] { background:#345b46 !important; height:2px; }
[data-testid="stExpander"] { border-color:var(--althea-line); border-radius:12px; background:transparent; }
[data-testid="stExpander"]:has([data-testid="stForm"]) { border:none; }
[data-testid="stExpander"] summary p { font-size:13px; font-weight:550; }
[data-testid="stVerticalBlockBorderWrapper"] > div { border-color:var(--althea-line) !important; border-radius:14px !important; }
[data-testid="stMetric"] { background:#fff; border:1px solid var(--althea-line); border-radius:12px; padding:16px 20px; }
[data-testid="stMetricLabel"] p { font-size:11px; color:var(--althea-muted); }
[data-testid="stMetricValue"] { font-size:26px; font-weight:500; letter-spacing:-1px; }
.process-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:26px; margin:22px 0 4px; }
.process-step { border-top:1px solid #dbe2d9; padding-top:16px; }
.process-step span { font-size:10px; color:#7b8b7d; letter-spacing:1px; }
.process-step h4 { font-size:13px; font-weight:600; margin:8px 0 6px; }
.process-step p { font-size:12px; line-height:1.65; color:#798179; margin:0; }
.turn { display:grid; grid-template-columns:88px minmax(0,1fr); gap:20px; padding:21px 0; border-bottom:1px solid #e7ebe4; }
.turn-time { font-size:11px; color:#7b867d; font-variant-numeric:tabular-nums; padding-top:3px; }
.turn-speaker { display:flex; gap:7px; align-items:center; color:#365f45; font-weight:600; font-size:12px; margin-bottom:7px; }
.turn-speaker::before { content:''; width:6px; height:6px; border-radius:50%; background:#7c9c80; flex-shrink:0; }
.turn-speaker.alternate { color:#796544; }
.turn-speaker.alternate::before { background:#b59d75; }
.turn-text { white-space:pre-wrap; font-size:14px; line-height:1.8; color:#354139; overflow-wrap:anywhere; }
.scope-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; margin:18px 0; }
.scope-item { padding:12px 14px; border-radius:8px; background:#eff3ec; overflow-wrap:anywhere; }
.scope-item span { font-size:10px; color:#7b867d; display:block; margin-bottom:5px; }
.scope-item strong { font-size:12px; font-weight:500; }
.footer-note { color:#869084; font-size:10px; letter-spacing:.2px; padding:24px 0 8px; }
@media(max-width:800px) {
 [data-testid="stMainBlockContainer"] { padding:1.7rem 1.3rem 3rem; }
 .hero h1 { letter-spacing:-1px; }
 .process-grid { gap:16px; }
 .scope-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
 .turn { grid-template-columns:66px minmax(0,1fr); gap:12px; }
 [data-testid="stTabs"] [role="tablist"] { gap:18px; }
 [data-testid="stForm"] { padding:18px; }
}
@media(max-width:480px) { .process-grid { grid-template-columns:1fr; gap:14px; } }

/* Full-width application shell */
[data-testid="stHeader"] { display:none; }
[data-testid="stMainBlockContainer"] { max-width:1200px; padding:1.4rem 2.5rem 4rem; }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
.st-key-top_navigation { border-bottom:1px solid #dfe5db; padding-bottom:18px; margin-bottom:8px; }
.st-key-top_navigation .brand { margin:0; height:40px; }
.st-key-top_navigation [data-testid="stButton"] button { border:0; background:transparent; color:#6b776c; border-radius:8px; }
.st-key-top_navigation button[kind="primary"] { background:#e7eee1 !important; border:0 !important; color:#294c36 !important; }
.st-key-top_navigation [data-testid="stHorizontalBlock"] { align-items:center; }
.landing-hero { display:grid; grid-template-columns:1.5fr 1fr; align-items:center; gap:45px; padding:20px 0 26px; }
.landing-hero h1 { font-size:clamp(30px,3.8vw,46px); font-weight:550; letter-spacing:-1.9px; line-height:1.13; margin:0 0 17px; padding:0; }
.landing-hero h1 span { color:#6b826c; }
.landing-hero p { color:#6b776c; font-size:14px; line-height:1.75; margin:0; }
.hero-tags { display:flex; gap:10px; margin-top:20px; flex-wrap:wrap; }
.hero-tags span { border:1px solid #dfe5da; border-radius:20px; padding:5px 11px; font-size:10px; color:#65745e; }
.hero-art svg { width:100%; max-height:230px; display:block; }
.st-key-audio_workspace { background:#fff; border:1px solid #dfe5db; border-radius:18px; padding:24px; box-shadow:0 8px 30px #203d2805; }
.workspace-heading { display:flex; align-items:center; gap:12px; margin-bottom:18px; }
.workspace-heading .mic-symbol { display:grid; place-items:center; border-radius:12px; background:#eef3e8; color:#41664c; width:42px; height:42px; }
.workspace-heading h3 { margin:0; font-size:17px !important; letter-spacing:-.3px; }
.workspace-heading h3,.guide-panel h3,.guide-step h4 { padding:0; }
.workspace-heading p { margin:4px 0 0; color:#798274; font-size:11px; }
[data-testid="stRadio"] [role="radiogroup"] { gap:5px; background:#f2f5ee; border-radius:10px; padding:4px; width:fit-content; margin-bottom:8px; }
[data-testid="stRadio"] label { padding:6px 12px; border-radius:7px; margin:0 !important; }
[data-testid="stRadio"] label:has(input:checked) { background:#fff; box-shadow:0 1px 4px #223d2212; }
[data-testid="stRadio"] label > div:first-child { display:none; }
[data-testid="stRadio"] label p { font-size:12px; }
[data-testid="stFileUploader"] section { padding:20px 14px; background:#fafbf8; }
[data-testid="stAudioInput"] { max-width:320px; }
.st-key-recorder_shortcut button { border-radius:22px !important; min-height:34px !important; }
.guide-panel { background:#edf2e6; border:1px solid #e1e8d8; border-radius:16px; padding:24px; }
.guide-panel h3 { font-size:16px !important; margin:0 0 8px; }
.guide-panel > p { font-size:12px; color:#6d7d64; line-height:1.7; margin:0 0 24px; }
.guide-step { display:grid; grid-template-columns:25px 1fr; gap:12px; margin:0 0 22px; }
.guide-step > span { display:grid; place-items:center; width:24px; height:24px; border-radius:50%; border:1px solid #cddbc0; font-size:10px; color:#6c815e; }
.guide-step h4 { margin:2px 0 5px; font-size:12px; font-weight:600; }
.guide-step p { margin:0; font-size:11px; line-height:1.7; color:#728069; }
.guide-note { padding-top:16px; border-top:1px solid #d9e2cf; font-size:10px; line-height:1.7; color:#77846e; }
.site-footer { margin-top:38px; border-top:1px solid #e2e7dd; padding-top:18px; color:#87917e; font-size:10px; display:flex; justify-content:space-between; }
@media(max-width:800px) {
 [data-testid="stMainBlockContainer"] { padding:1rem 1.1rem 3rem; }
 .landing-hero { gap:14px; grid-template-columns:1.4fr 1fr; padding:20px 0; }
 .landing-hero h1 { letter-spacing:-1px; }
 .landing-hero p { font-size:12px; }
 .desktop-break { display:none; }
 .st-key-audio_workspace { padding:18px; }
}
@media(max-width:560px) { .landing-hero { grid-template-columns:1fr; } .hero-art { display:none; } .brand-name {font-size:19px;} .brand-mark {width:27px;height:27px;} }

</style>
"""


def apply_style(st):
    st.markdown(STYLES,unsafe_allow_html=True)


def header(st, *, has_result=False):
    if has_result:
        st.markdown('<div class="hero compact"><div class="eyebrow">Your workspace</div><h1>A closer look at the conversation.</h1></div>',unsafe_allow_html=True)
        return
    bars=''.join(f'<rect x="{35+i*7}" y="{90-h/2}" width="3" height="{h}" rx="1.5" fill="{ "#c4dfad" if i<20 else "#668979"}"/>' for i,h in enumerate([10,16,26,18,40,55,32,20,45,66,38,18,30,52,75,43,24,14,36,60,48,22,35,54,28,14,20,36,18,10,22,12]))
    artwork='<svg viewBox="0 0 340 210" role="img" aria-label="Illustration of an audio waveform connected to a transcript"><rect x="12" y="25" width="285" height="132" rx="22" fill="#244d3b"/><circle cx="39" cy="49" r="4" fill="#c4dfad"/><text x="51" y="53" fill="#d9e6dd" font-size="9" font-family="sans-serif" letter-spacing="1.5">THE CONVERSATION</text>'+bars+'<path d="M36 131H245" stroke="#547661" stroke-width="2"/><circle cx="133" cy="131" r="4" fill="#d8e8c9"/><rect x="177" y="116" width="149" height="79" rx="13" fill="white" stroke="#d9e2d6"/><circle cx="198" cy="139" r="7" fill="#edf3e8"/><path d="m195 139 2 2 4-4" fill="none" stroke="#416b4c" stroke-width="1.5"/><text x="212" y="142" fill="#41634b" font-family="sans-serif" font-size="9">A clearer perspective</text><path d="M193 157H307M193 168H292M193 179H267" stroke="#dfe7dc" stroke-width="4" stroke-linecap="round"/></svg>'
    st.markdown('<div class="landing-hero"><div><div class="eyebrow">Listen closer. Understand more.</div><h1>Every conversation.<br><span>A clearer perspective.</span></h1><p>Turn debate audio into a transcript you can review,<br class="desktop-break"> claims you can compare, and evidence you can follow.</p><div class="hero-tags"><span>English audio</span><span>Up to 5 minutes</span><span>MP3 & WAV</span></div></div><div class="hero-art">'+artwork+'</div></div>',unsafe_allow_html=True)


def process_guide(st):
    st.markdown('<div class="process-grid">'
        '<div class="process-step"><span>01 / LISTEN</span><h4>Start with the conversation</h4><p>Add a recording or explore the fictional sample.</p></div>'
        '<div class="process-step"><span>02 / UNDERSTAND</span><h4>See each claim in context</h4><p>Review exact words, speakers, numbers and scope.</p></div>'
        '<div class="process-step"><span>03 / VERIFY</span><h4>Follow the evidence</h4><p>Choose disagreements to check against sources.</p></div></div>',unsafe_allow_html=True)


def transcript_turn(st, *, time, speaker, text, alternate=False):
    st.markdown('<div class="turn"><div class="turn-time">'+escape(time)+'</div><div><div class="turn-speaker'+(' alternate' if alternate else '')+'">'+escape(speaker)+'</div><div class="turn-text">'+escape(text)+'</div></div></div>',unsafe_allow_html=True)


def scope_details(st, claim):
    fields=[('subject','Subject'),('metric','Metric'),('period','Period'),('geography','Geography'),('population','Population'),('measurement_basis','Measurement basis')]
    st.markdown('<div class="scope-grid">'+''.join('<div class="scope-item"><span>'+label+'</span><strong>'+escape(claim[key] or 'Unknown')+'</strong></div>' for key,label in fields)+'</div>',unsafe_allow_html=True)
