const states = {
  outside_summary_window:['本篇不生成 AI 要点','仅为最近三年发布的政策生成要点，本篇仍可阅读正文。'],
  publication_date_unknown:['发布日期待确认','确认属于最近三年的政策后才会生成要点，可先阅读正文。'],
  pending:['AI 要点待生成','新收录内容将自动生成要点，可先阅读正文。'],
  queued:['AI 要点排队中','正在逐批补齐历史内容，生成后会自动显示。'],
  generating:['AI 正在整理要点','正在结合原文生成并核验引句，请稍候。'],
  retrying:['AI 要点生成重试中','上次生成未完成，系统会自动重试。'],
  service_paused:['AI 要点服务暂不可用','后台已暂停请求并安排重试，可先阅读正文。'],
  failed:['AI 要点暂未生成','多次生成或原文依据校验未通过，等待后台处理。'],
  not_configured:['AI 要点服务尚未启用','内容已收录，服务接入后会自动补齐要点。'],
  waiting_content:['等待原文内容补齐','当前正文不足，正在等待附件文字收录。'],
  insufficient_content:['原文文字不足','当前收录内容不足以生成可靠要点，请查看正文或官网附件。']
};
function view(meta = {}) {
  const state = meta.state || 'unknown', message = states[state] || ['本篇暂未生成要点','可切换正文，或查看官方来源。'];
  const scopes = {body:'依据已收录正文生成',body_excerpt:'依据正文前段生成，未覆盖全文',attachments:'依据已提取的附件文字生成',attachments_excerpt:'依据部分附件文字生成，未覆盖完整附件'};
  return {state,title:message[0],note:message[1],scope:scopes[meta.scope] || '',
    poll:['pending','queued','generating','retrying'].includes(state),
    refresh:['pending','queued','generating','retrying','failed','service_paused','not_configured','waiting_content'].includes(state)};
}
module.exports = {view};
