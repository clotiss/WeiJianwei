function view(meta = {}) {
  const state = meta.state || 'unknown';
  const scopes = {body:'依据已收录正文生成',body_excerpt:'依据正文前段生成，未覆盖全文',attachments:'依据已提取的附件文字生成',attachments_excerpt:'依据部分附件文字生成，未覆盖完整附件'};
  return {state,title:'本篇暂无要点',note:'可阅读正文，或查看官方原文。',scope:scopes[meta.scope] || '',
    poll:['pending','queued','generating','retrying'].includes(state),
    refresh:['pending','queued','generating','retrying','failed','service_paused','not_configured','waiting_content'].includes(state)};
}
module.exports = {view};
