#!/usr/bin/env node
// 只替换 GitHub 传输：同一路由、分页外壳、状态/实体格式，不提供判定。
const fs = require("node:fs");
const args = process.argv.slice(2);
const route = args.at(-1)?.replace(/^repos\/Newchanlun\/NewChanlun\//, "");
const routes = JSON.parse(fs.readFileSync(process.env.AT18_TEST_GITHUB, "utf8"));
if (args[0] !== "api" || !Object.hasOwn(routes, route)) {
  process.exitCode = 1;
} else {
  const value = routes[route];
  process.stdout.write(JSON.stringify(args.includes("--paginate") ? [value] : value));
}
