const names = require('../config/regions');
function decode(value) {
  try { return decodeURIComponent(value || ''); } catch (_) { return ''; }
}
function fromRoute(options = {}) {
  return { region:decode(options.region) || 'CN', include_national:options.include_national === 'true' || options.include_national === true,
    category:decode(options.category) || '全部', doc_type:decode(options.doc_type) || '全部类型', published_since:decode(options.published_since) };
}
function toQuery(filters) {
  return Object.entries(filters).map(([key, value]) => encodeURIComponent(key) + '=' + encodeURIComponent(value)).join('&');
}
function label(filters) {
  const region = names[filters.region] || names.CN;
  return region + (filters.region && filters.region !== 'CN' && filters.include_national ? ' + 国家' : '') +
    ' · ' + (filters.category || '全部') + ' · ' + (filters.doc_type || '全部类型') +
    (filters.published_since ? ' · ' + filters.published_since + ' 起' : '');
}
function since(days) {
  if (!days) return '';
  const date=new Date(); date.setDate(date.getDate()-Number(days));
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
}
module.exports = { fromRoute, toQuery, label, since };
