import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import LoginPage from "@/app/login/page";
import RegisterPage from "@/app/register/page";
import AuthCallbackPage from "@/app/auth/callback/page";
import { MATERIALS_DOWNLOAD_RETURN, rememberMaterialsAuthReturn } from "@/lib/materials-auth-return";

const api = vi.hoisted(() => ({ login: vi.fn(), register: vi.fn(), me: vi.fn(), push: vi.fn(), replace: vi.fn(), notify: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useRouter: () => api, useSearchParams: () => api.params }));
vi.mock("@/lib/auth-session", () => ({ notifyAuthChange: api.notify }));
vi.mock("@/lib/api", () => ({ login: api.login, register: api.register, me: api.me,
  PUBLIC_API_BASE: "https://api.jzis.org/sclib/v1", ApiError: class extends Error {},
  friendlyErrorMessage: (_error: unknown, fallback: string) => fallback }));
beforeEach(() => { vi.clearAllMocks(); api.login.mockResolvedValue({}); api.register.mockResolvedValue({}); api.me.mockResolvedValue({id:"owned-member"}); });
afterEach(() => { window.history.replaceState(null,"","/"); sessionStorage.clear(); });
function setReturn(route = "/login", next = MATERIALS_DOWNLOAD_RETURN) {
  window.history.replaceState(null,"",route+"?next="+encodeURIComponent(next));
}
async function signIn() {
  fireEvent.change(screen.getByLabelText("Email"),{target:{value:"owned@example.invalid"}});
  fireEvent.change(screen.getByLabelText(/Password/),{target:{value:"owned-fixture-password"}});
  fireEvent.click(screen.getByRole("button",{name:"Sign in",exact:true}));
}
it("returns a dataset user to Materials after email sign-in", async () => {
  setReturn(); render(<LoginPage />);
  await signIn();
  await waitFor(() => expect(api.push).toHaveBeenCalledWith(MATERIALS_DOWNLOAD_RETURN));
  expect(screen.getByRole("link",{name:"Create an account"})).toHaveAttribute("href","/register?next=%2Fmaterials%23materials-downloads");
});
it("keeps the normal dashboard destination for an invalid return path", async () => {
  setReturn("/login","//example.com"); render(<LoginPage />); await signIn();
  await waitFor(() => expect(api.push).toHaveBeenCalledWith("/dashboard"));
});
it("keeps email verification and a Materials sign-in link after registration", async () => {
  setReturn("/register"); render(<RegisterPage />);
  fireEvent.change(screen.getByLabelText("Email *"),{target:{value:"owned@example.invalid"}});
  fireEvent.change(screen.getByLabelText(/Password \*/),{target:{value:"owned-fixture-password"}});
  fireEvent.change(screen.getByLabelText("Full name *"),{target:{value:"Owned fixture"}});
  fireEvent.click(screen.getByRole("button",{name:"Create account",exact:true}));
  expect(await screen.findByRole("heading",{name:"Check your email"})).toBeVisible();
  expect(screen.getByRole("link",{name:"sign in to view dataset downloads"})).toHaveAttribute("href","/login?next=%2Fmaterials%23materials-downloads");
});
it("restores the one-time Materials destination after an OAuth session is confirmed", async () => {
  rememberMaterialsAuthReturn(MATERIALS_DOWNLOAD_RETURN);
  render(<AuthCallbackPage />);
  await waitFor(() => expect(api.replace).toHaveBeenCalledWith(MATERIALS_DOWNLOAD_RETURN));
  expect(api.notify).toHaveBeenCalledOnce();
});
