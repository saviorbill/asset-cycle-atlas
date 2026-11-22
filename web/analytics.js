/* ------------------------------------------------------------------
   访问统计（默认全部关闭：ID 留空则不会发出任何请求）
   填好下面的 ID 后，随站点一起部署即可开始统计。
   ------------------------------------------------------------------ */
(function () {
  var CFG = {
    // ① 百度统计（国内最稳，推荐）
    //    获取：https://tongji.baidu.com → 管理 → 新增网站 → 复制代码里的 hm.js? 后面那串 ID
    baiduId: '',

    // ② Cloudflare Web Analytics（免费、无 Cookie、隐私友好）
    //    获取：Cloudflare Dashboard → Analytics → Web Analytics → 添加站点 → 复制 token
    cfToken: ''
  };

  // ① 百度统计
  if (CFG.baiduId) {
    window._hmt = window._hmt || [];
    var hm = document.createElement('script');
    hm.src = 'https://hm.baidu.com/hm.js?' + CFG.baiduId;
    hm.async = true;
    var s0 = document.getElementsByTagName('script')[0];
    if (s0 && s0.parentNode) s0.parentNode.insertBefore(hm, s0); else document.head.appendChild(hm);
  }

  // ② Cloudflare Web Analytics
  if (CFG.cfToken) {
    var cf = document.createElement('script');
    cf.defer = true;
    cf.src = 'https://static.cloudflareinsights.com/beacon.min.js';
    cf.setAttribute('data-cf-beacon', JSON.stringify({ token: CFG.cfToken }));
    document.head.appendChild(cf);
  }
})();
