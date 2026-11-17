const names = require('../config/regions');
function decode(value) {
  try { return decodeURIComponent(value || ''); } catch (_) { return ''; }
}
function fromRoute(options = {}) {
  return { region:decode(options.region), include_national:options.include_national !== 'false',
    category:decode(options.category) || '全部', doc_type:decode(options.doc_type) || '全部类型' };
}
function toQuery(filters) {
  return Object.entries(filters).map(([key, value]) => encodeURIComponent(key) + '=' + encodeURIComponent(value)).join('&');
}
function label(filters) {
  const region = names[filters.region] || '全国';
  return region + (filters.region && filters.region !== 'CN' && filters.include_national ? ' + 国家' : '') +
    ' · ' + (filters.category || '全部') + ' · ' + (filters.doc_type || '全部类型');
}
module.exports = { fromRoute, toQuery, label };
