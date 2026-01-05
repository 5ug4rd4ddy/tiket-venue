// language + theme + interactions
let currentLang = 'id';
function applyLang(lang){
  currentLang = lang;
  document.getElementById('langLabel').textContent = lang === 'id' ? 'ID' : 'EN';
  document.getElementById('langFlag').src = lang === 'id' ? 'https://flagcdn.com/id.svg' : 'https://flagcdn.com/gb.svg';
  // small translations
  const t = {
    id: { 'Tipe kunjungan':'Tipe kunjungan','Tanggal kunjungan':'Tanggal kunjungan','Pilih tiket':'Pilih tiket','Tambahan':'Tambahan','Ringkasan':'Ringkasan','Pesan Tiket':'Pesan Tiket','Pesan':'Pesan' },
    en: { 'Tipe kunjungan':'Visit type','Tanggal kunjungan':'Visit date','Pilih tiket':'Choose tickets','Tambahan':'Add-ons','Ringkasan':'Summary','Pesan Tiket':'Book tickets','Pesan':'Book' }
  };
  document.querySelectorAll('.label-lg').forEach(el=>{ const key = el.textContent.trim(); if(t[lang] && t[lang][key]) el.textContent = t[lang][key]; });
  document.getElementById('checkoutBtnDesktop').textContent = (t[lang] && t[lang]['Pesan Tiket']) || document.getElementById('checkoutBtnDesktop').textContent;
  document.getElementById('checkoutBtnMobile').textContent = (t[lang] && t[lang]['Pesan']) || document.getElementById('checkoutBtnMobile').textContent;
}

document.getElementById('langSwitch').addEventListener('click', ()=>{
  const menu = document.getElementById('langMenu');
  menu.classList.toggle('hidden');
});
document.querySelectorAll('#langMenu [data-lang]').forEach(btn=>{
  btn.addEventListener('click', ()=>{ const l = btn.getAttribute('data-lang'); applyLang(l); document.getElementById('langMenu').classList.add('hidden'); });
});
applyLang('id');

// theme
const saved = localStorage.getItem('theme');
const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
if (saved === 'dark' || (!saved && prefersDark)) document.documentElement.classList.add('dark');
function updateThemeIcon(){ const isDark = document.documentElement.classList.contains('dark'); document.getElementById('iconMoon').classList.toggle('hidden', isDark); document.getElementById('iconSun').classList.toggle('hidden', !isDark); }
updateThemeIcon();
document.getElementById('themeToggle').addEventListener('click', ()=>{ const isDark = document.documentElement.classList.toggle('dark'); localStorage.setItem('theme', isDark ? 'dark' : 'light'); updateThemeIcon(); });

// flatpickr init
document.addEventListener('DOMContentLoaded', function(){
  if (typeof flatpickr !== 'undefined'){
    flatpickr('#datePicker', { minDate: 'today', altInput: true, altFormat: 'F j, Y', dateFormat: 'Y-m-d', onOpen: function(){ document.getElementById('datePicker').classList.add('active-border'); document.getElementById('datePicker').classList.remove('inactive-border'); }, onClose: function(){ if(!document.getElementById('datePicker')._flatpickr.selectedDates.length){ document.getElementById('datePicker').classList.remove('active-border'); document.getElementById('datePicker').classList.add('inactive-border'); } }, onChange: function(selectedDates, dateStr, instance){ document.getElementById('summaryDate').textContent = instance.altInput.value; updateSummary(); document.getElementById('datePicker').classList.add('active-border'); document.getElementById('datePicker').classList.remove('inactive-border'); } });
    // set initial inactive look
    document.getElementById('datePicker').classList.add('inactive-border');
  } else console.warn('flatpickr not loaded');
});

// data model
const prices = { wahana:120000, atraksi:80000, stroller:30000, fastpass:50000 };
const counts = { 'wahana-adult':1, 'wahana-child':0, 'atraksi-adult':0, 'atraksi-child':0 };
const addons = { stroller:false, fastpass:false };

function numberWithCommas(x){ return x.toLocaleString('id-ID'); }
function calcTotal(){
  const wahanaTotal = counts['wahana-adult'] * prices.wahana + counts['wahana-child'] * Math.round(prices.wahana * 0.66);
  const atraksiTotal = counts['atraksi-adult'] * prices.atraksi + counts['atraksi-child'] * Math.round(prices.atraksi * 0.66);
  let total = wahanaTotal + atraksiTotal;
  if (addons.stroller) total += prices.stroller;
  if (addons.fastpass) total += prices.fastpass;
  return total;
}

function updateSummary(){
  const typeEl = document.querySelector('[name=visitType]:checked');
  const type = typeEl ? (typeEl.value) : 'personal';
  document.getElementById('summaryType').textContent = type === 'personal' ? (currentLang==='id'?'Personal':'Personal') : (currentLang==='id'?'Group':'Group');
  document.getElementById('summaryWahana').textContent = `D${counts['wahana-adult']} / C${counts['wahana-child']}`;
  document.getElementById('summaryAtraksi').textContent = `D${counts['atraksi-adult']} / C${counts['atraksi-child']}`;
  const addonList = [];
  if (addons.stroller) addonList.push('Stroller');
  if (addons.fastpass) addonList.push('Fast Pass');
  document.getElementById('summaryAddons').textContent = addonList.length ? addonList.join(', ') : '-';
  const total = calcTotal();
  document.getElementById('summaryTotal').textContent = 'Rp ' + numberWithCommas(total);
  document.getElementById('bottomTotal').textContent = 'Rp ' + numberWithCommas(total);
}

// qty buttons
document.querySelectorAll('.qty-circle').forEach(btn => {
  btn.addEventListener('click', () => {
    const type = btn.getAttribute('data-type');
    const action = btn.getAttribute('data-action');
    if (!type) return;
    if (action === 'increase') counts[type] = Math.min(20, counts[type] + 1);
    else counts[type] = Math.max(0, counts[type] - 1);
    const outEl = document.getElementById(type + '-count');
    if (outEl) outEl.textContent = counts[type];
    updateSummary();
  });
});

// addon toggle — update border color when selected
document.querySelectorAll('.addon-card').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.getAttribute('data-addon');
    const selected = btn.getAttribute('data-selected') === 'true';
    btn.setAttribute('data-selected', (!selected).toString());
    addons[key] = !selected;
    // toggle border color
    btn.classList.toggle('active-border', addons[key]);
    btn.classList.toggle('inactive-border', !addons[key]);
    updateSummary();
  });
});

// visit type animation + show/hide group form
function setTypeStyle(t){
  const p = document.getElementById('personalLabel');
  const g = document.getElementById('groupLabel');
  const groupForm = document.getElementById('groupForm');
  if (t === 'personal'){
    p.classList.add('selected'); g.classList.remove('selected');
    groupForm.classList.add('hidden');
  } else if (t === 'group') {
    g.classList.add('selected'); p.classList.remove('selected');
    groupForm.classList.remove('hidden');
  }
  updateSummary();
}
document.getElementById('personalLabel').addEventListener('click', ()=>{ document.getElementById('visitPersonal').checked = true; setTypeStyle('personal'); });
document.getElementById('groupLabel').addEventListener('click', ()=>{ document.getElementById('visitGroup').checked = true; setTypeStyle('group'); });

// initialize visit type default to personal
setTypeStyle('personal');

// checkout
function checkout(){
  const date = (document.getElementById('datePicker')._flatpickr) ? document.getElementById('datePicker')._flatpickr.input.value : '';
  if (!date){ alert((currentLang==='id')?`Pilih tanggal kunjungan terlebih dahulu.`:`Please choose a visit date first.`); return; }
  const payload = { type: (document.querySelector('[name=visitType]:checked') || {}).value || 'personal', date, counts: { ...counts }, addons: { ...addons }, total: calcTotal() };
  alert(`${currentLang==='id' ? 'Pesanan:' : 'Order:'}
${JSON.stringify(payload, null, 2)}`);
}
document.getElementById('checkoutBtnDesktop').addEventListener('click', checkout);
document.getElementById('checkoutBtnMobile').addEventListener('click', checkout);

// init
updateSummary();