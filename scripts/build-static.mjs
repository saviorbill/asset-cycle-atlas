import { cpSync, rmSync } from 'node:fs';

// 原项目是无打包依赖的静态站点；构建仅复制可部署文件，保留懒加载数据路径。
rmSync('dist', { recursive: true, force: true });
cpSync('web', 'dist', {
  recursive: true,
  filter: src => !/(^|[\\/])dist([\\/]|$)/.test(src)
});
console.log('Static site built at dist/');
