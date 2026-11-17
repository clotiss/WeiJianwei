const api = require('./api');
// Page advances only after success; a new query supersedes old in-flight responses.
function load(page, key, request, nextPage = 1) {
  const id = page._listRequest = (page._listRequest || 0) + 1;
  page.setData({loading:true, loadError:false, errorText:''});
  return request(nextPage).then(res => {
    if (id !== page._listRequest) return;
    const items = nextPage === 1 ? res.items : page.data[key].concat(res.items);
    page.setData({[key]:items, total:res.total, page:nextPage, loading:false, contentStatus:res.contentStatus || {},
      hasMore:items.length < res.total && res.items.length > 0});
  }).catch(error => {
    if (id !== page._listRequest) return;
    page.setData({loading:false, loadError:true, errorText:api.errorMessage(error)});
  });
}
module.exports = {load};
