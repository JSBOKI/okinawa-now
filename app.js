const TABS=[["movies","🎬 Movies"],["events","🎉 Events & Festivals"],["concerts","🎶 Concerts & Nightlife"],["family","🧒 Family & Kids"],["outdoors","🏖️ Outdoors & Beaches"],["food","🍜 Food & Markets"],["onbase","🇺🇸 On-Base"]];
const REGIONS=[["okinawa","🌺 Okinawa"],["kyushu","♨️ Fukuoka–Beppu"]];
const AREASBY={okinawa:[["all","All areas"],["north","North"],["central","Central"],["south","South"]],
 kyushu:[["all","All areas"],["fukuoka","Fukuoka / Dazaifu"],["kitakyushu","Kitakyushu / Kokura"],["kurume","Kurume"],["nakatsu-usa","Nakatsu / Usa"],["beppu","Beppu / Yufuin"],["oita","Oita city"],["oita-other","Rest of Oita"]]};
const st={tab:location.hash.slice(1)||"movies",area:"all",date:"today",movieDay:null,region:localStorage.getItem("fap-region")||"okinawa"};
let M=null,E=null;
const $=s=>document.querySelector(s);
const esc=s=>(s??"").toString().replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function jstNow(){return new Date(Date.now()+9*3600e3)}
function jstToday(){return jstNow().toISOString().slice(0,10)}
function addDays(d,n){const x=new Date(d+"T00:00:00Z");x.setUTCDate(x.getUTCDate()+n);return x.toISOString().slice(0,10)}
function dow(d){return new Date(d+"T00:00:00Z").toLocaleDateString("en-US",{weekday:"short",timeZone:"UTC"})}
function nice(d){return new Date(d+"T00:00:00Z").toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",timeZone:"UTC"})}
function range(){const t=jstToday();if(st.date==="today")return[t,t];if(st.date==="week")return[t,addDays(t,6)];if(st.date==="all")return[t,addDays(t,60)];
  const wd=new Date(t+"T00:00:00Z").getUTCDay();let sat=addDays(t,(6-wd+7)%7);if(wd===0)return[t,t];return[wd===5?t:sat,addDays(sat,1)]}
async function load(){
  const [m,e]=await Promise.all([fetch("data/movies.json?"+Date.now()).then(r=>r.json()),fetch("data/events.json?"+Date.now()).then(r=>r.json())]);
  M=m;E=e;$("#checked").textContent="Updated "+m.checked_at;render();}
function chips(el,items,cur,fn){el.innerHTML=items.map(([k,l])=>`<button class="${k===cur?"on":""}" data-k="${k}">${l}</button>`).join("");el.querySelectorAll("button").forEach(b=>b.onclick=()=>fn(b.dataset.k))}
function render(){
  chips($("#tabs"),TABS,st.tab,k=>{st.tab=k;location.hash=k;render();scrollTo(0,0)});
  chips($("#regionf"),REGIONS,st.region,k=>{st.region=k;st.area="all";localStorage.setItem("fap-region",k);render();scrollTo(0,0)});
  chips($("#areaf"),AREASBY[st.region],st.area,k=>{st.area=k;render()});
  if(st.tab==="movies"){const t=jstToday();const days=(M.days||[]).filter(d=>d>=t);if(!st.movieDay||!days.includes(st.movieDay))st.movieDay=days[0]||t;
    chips($("#datef"),days.map((d,i)=>[d,i===0?"Today":i===1?"Tomorrow":nice(d)]),st.movieDay,k=>{st.movieDay=k;render()});renderMovies();}
  else{chips($("#datef"),[["today","Today"],["weekend","This weekend"],["week","This week"],["all","All upcoming"]],st.date,k=>{st.date=k;render()});renderEvents();}
  renderSources();}
function regOk(x){return (x.region||"okinawa")===st.region}
function areaOk(a){return st.area==="all"||a===st.area}
function renderMovies(){
  const day=st.movieDay,now=jstNow().toISOString().slice(11,16),isToday=day===jstToday();
  const ths=M.theaters.filter(t=>regOk(t)&&areaOk(t.area));
  let h=`<div class="jump">${ths.map(t=>`<a href="#th-${t.id}" onclick="document.getElementById('th-${t.id}').scrollIntoView({behavior:'smooth'});return false">${esc(t.name)}</a>`).join("")}</div>`;
  for(const t of ths){
    const films=t.movies.map(f=>({...f,today:f.showtimes.filter(s=>s.date===day)})).filter(f=>f.today.length);
    h+=`<section class="card" id="th-${t.id}"><div class="th-h"><h2>${esc(t.name)}</h2><span>${t.featured?'<span class="badge feat">Featured</span>':""}<span class="badge">${t.area}</span></span></div>
    <div class="muted">${esc(t.name_ja||"")} ${esc(t.city||"")} · <a href="${esc(t.url)}" target="_blank" rel="noopener">source</a>${t.price?" · "+esc(t.price):""}</div>
    ${t.notes?`<div class="muted" style="margin-top:3px">${esc(t.notes)}</div>`:""}`;
    if(t.status!=="ok"){h+=`<p><span class="badge bad">Unavailable</span> Couldn't read this theater's schedule today. ${esc(t.error||"")} Check the <a href="${esc(t.url)}" target="_blank">official site</a>.</p></section>`;continue}
    if(!films.length){h+=`<p class="muted">No showtimes listed for ${nice(day)}.</p></section>`;continue}
    for(const f of films){
      const meta=[f.rating,f.runtime?f.runtime+" min":null,f.year,f.format].filter(Boolean).map(esc).join(" · ");
      h+=`<div class="film">${f.poster?`<img loading="lazy" src="${esc(f.poster)}" alt="">`:""}<div style="flex:1;min-width:0">
      <h3>${esc(f.title)}</h3>${f.title_ja&&f.title_ja!==f.title?`<div class="ja">${esc(f.title_ja)}</div>`:""}
      <div class="muted">${meta}</div>
      <div class="times">${f.today.map(s=>`<span class="t ${isToday&&s.time<now?"past":""}">${s.time}${s.tag?`<small>${esc(s.tag)}</small>`:""}</span>`).join("")}</div>
      ${f.synopsis||f.synopsis_ja?`<details><summary>Synopsis</summary>${f.synopsis?`<p class="syn">${esc(f.synopsis)}</p>`:`<p class="syn muted">(English translation unavailable this run)</p>`}${f.synopsis_ja?`<p class="syn ja">${esc(f.synopsis_ja)}</p>`:""}</details>`:""}
      <div class="muted"><a href="${esc(f.source)}" target="_blank" rel="noopener">source</a>${f.price?" · "+esc(f.price):""}${f.trailer?` · <a href="${esc(f.trailer)}" target="_blank">trailer</a>`:""}</div></div></div>`;}
    h+=`</section>`;}
  h+=`<div class="card muted">${(M.notes||[]).map(esc).join("<br>")}<br>Times tagged <b>Sub</b> are in the original language (usually English) with Japanese subtitles. <b>Dub</b> means dubbed into Japanese.</div>`;
  $("#main").innerHTML=h;}
function renderEvents(){
  const [a,b]=range();
  let items=E.items.filter(e=>e.category===st.tab||(st.tab==="events"&&false)).filter(e=>regOk(e)&&areaOk(e.area)).filter(e=>{const s=e.start||a,en=e.end||s;return s<=b&&en>=a});
  items.sort((x,y)=>{const sx=(x.start>=a)?0:1,sy=(y.start>=a)?0:1;return sx-sy||(x.start||"").localeCompare(y.start||"")||(x.time||"").localeCompare(y.time||"")});
  let h="";
  if(st.tab==="onbase"&&st.region==="kyushu")h+=`<div class="card muted">There are no US bases in the Fukuoka–Beppu corridor. (Sasebo and Iwakuni are outside this area.)</div>`;
  else if(st.tab==="onbase")h+=`<div class="card muted">Kadena FSS events come from kadenafss.com. MCCS (Foster/Courtney/Kinser/Schwab) event pages block automated reads, so check <a href="https://www.okinawa.usmc-mccs.org/" target="_blank">okinawa.usmc-mccs.org</a>. Base movie times are in the 🎬 Movies tab.</div>`;
  if(!items.length)h+=`<div class="empty">Nothing listed for this filter.</div>`;
  for(const e of items){
    const ongoing=e.start&&e.start<a;const when=e.start?(e.start===e.end||!e.end?nice(e.start):`${nice(e.start)} – ${nice(e.end)}`):"";
    h+=`<div class="card ev"><h3>${esc(e.title||e.title_ja)}</h3>${e.title_ja&&e.title?`<div class="ja">${esc(e.title_ja)}</div>`:""}
    <div class="meta">📅 ${when}${e.time?" · "+esc(e.time):""}${ongoing?' <span class="badge">ongoing</span>':""}</div>
    <div class="meta">📍 ${esc(e.venue||"")}${e.city?" · "+esc(e.city):""} <span class="badge">${e.area}</span></div>
    ${e.description&&e.category==="onbase"?`<p class="syn">${esc(e.description)}</p>`:""}${e.price?`<div class="meta">💴 ${esc(e.price)}</div>`:""}
    <div class="meta"><a href="${esc(e.source)}" target="_blank" rel="noopener">${esc(e.src_name||"source")}</a></div></div>`;}
  $("#main").innerHTML=h;}
function renderSources(){const s=[...(M.sources||[]),...(E.sources||[])];
  $("#sources").innerHTML="<p><b>Sources this refresh</b></p>"+s.map(x=>`<div class="src"><span class="dot ${x.status==="ok"?"":"bad"}"></span><a href="${esc(x.url)}" target="_blank">${esc(x.name)}</a> ${x.status==="ok"?x.items+" items":"unavailable: "+esc(x.note)}</div>`).join("");}
window.onhashchange=()=>{const k=location.hash.slice(1);if(TABS.some(t=>t[0]===k)&&k!==st.tab){st.tab=k;render()}};
load().catch(e=>$("#main").innerHTML=`<div class="empty">Couldn't load data: ${esc(e)}</div>`);
