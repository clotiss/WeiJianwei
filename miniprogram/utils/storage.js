const FAVORITES_KEY = 'favorites';

function getFavorites() {
  try {
    return wx.getStorageSync(FAVORITES_KEY) || [];
  } catch (e) {
    return [];
  }
}

function setFavorites(favs) {
  wx.setStorageSync(FAVORITES_KEY, favs);
}

function isFavorited(docId) {
  const favs = getFavorites();
  return favs.some(f => f.id === docId);
}

function toggleFavorite(doc) {
  let favs = getFavorites();
  const idx = favs.findIndex(f => f.id === doc.id);
  if (idx >= 0) {
    favs.splice(idx, 1);
    setFavorites(favs);
    return false; // 已取消收藏
  } else {
    favs.push(doc);
    setFavorites(favs);
    return true; // 已收藏
  }
}

module.exports = { getFavorites, setFavorites, isFavorited, toggleFavorite };
