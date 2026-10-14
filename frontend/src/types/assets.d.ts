// 静态资源 / 样式表的副作用导入声明。
//
// Next.js 自带类型（next/types/global.d.ts）只声明了 *.module.css，
// 没有声明纯 *.css。当 TS 检查副作用导入时（编辑器的语言服务、
// 或开启 noUncheckedSideEffectImports），`import "./globals.css"`
// 会报 ts(2882/2307)「找不到模块或其类型声明」。这里补上声明。
//
// 注意：next-env.d.ts 由 Next 自动生成，不要手改，故单独放此文件。

declare module "*.css";
