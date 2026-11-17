// Render the reviewed vector icons as transparent PNG assets for WeChat.
// npm install --prefix .runtime/icon-render --ignore-scripts @resvg/resvg-js
const fs=require('node:fs'),path=require('node:path');
const {Resvg}=require('../.runtime/icon-render/node_modules/@resvg/resvg-js');
const root=path.resolve(__dirname,'../miniprogram/assets/icons');
const icons=JSON.parse(fs.readFileSync(path.join(root,'sources.json'),'utf8'));
const colors={blue:'#2269b0',muted:'#8a9aa5',teal:'#187c80',white:'#ffffff'};
const variants={policy:['muted','blue'],bell:['muted','blue'],user:['muted','blue'],search:['muted'],pin:['blue'],down:['muted'],filter:['muted'],arrow:['teal'],book:['muted','blue'],shield:['teal'],spark:['blue'],link:['white'],close:['muted'],settings:['muted'],chevron:['muted'],clock:['muted'],refresh:['muted']};
for(const [name,tones] of Object.entries(variants))for(const tone of tones){
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 24 24" fill="none" stroke="${colors[tone]}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[name]}</svg>`;
 fs.writeFileSync(path.join(root,`${name}-${tone}.png`),new Resvg(svg).render().asPng());
}
console.log('Prototype icons rendered');
