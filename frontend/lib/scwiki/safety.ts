export function safeUrl(value: string): string {
  if(/[\u0000-\u0020\u007f]/.test(value)) return "";
  if(value.startsWith("#")) return /^#[a-zA-Z0-9_-]+$/.test(value)?value:"";
  if(value.startsWith("/") && !value.startsWith("//") && !value.includes("\\")) return value;
  try { const u=new URL(value); return u.protocol==="https:" && !u.username && !u.password?u.href:""; } catch { return ""; }
}
export function sectionId(text: string): string {
  const item=/^([I-M][0-9]+) — /u.exec(text);
  return (item?item[1]:text).toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
}
