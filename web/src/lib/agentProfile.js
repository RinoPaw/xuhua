export function agentProfile(pathname = "") {
  const shizha = /^\/shizha\/?$/u.test(String(pathname));
  return shizha
    ? { name: "识诈", shizha: true, apiBase: "/shizha", noun: "案例", library: "反诈案例" }
    : { name: "叙华", shizha: false, apiBase: "", noun: "项目", library: "非遗项目" };
}
