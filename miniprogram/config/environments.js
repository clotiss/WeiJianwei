// 后端地址统一在此配置。体验版必须配置已部署且通过 HTTPS 校验的 V2 服务。
const profiles = {
  develop: { USE_POLICY_V2: true, API_V2_BASE: 'http://127.0.0.1:8892/api/v2' },
  trial: { USE_POLICY_V2: true, API_V2_BASE: '' },
  release: { USE_POLICY_V2: false, API_V2_BASE: 'https://wjwjwjw.top/api/v2' }
};
function resolveEnvironment(envVersion) {
  const environment = Object.prototype.hasOwnProperty.call(profiles, envVersion) ? envVersion : 'release';
  return { API_BASE: 'https://wjwjwjw.top/api/v1', ...profiles[environment], environment };
}
module.exports = { profiles, resolveEnvironment };
