import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CookieConsentBanner,
  loadConsent,
} from "@/components/CookieConsent";
import { GuestBanner } from "@/components/GuestBanner";

describe("CookieConsentBanner", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("persists an explicit analytics rejection and closes the banner", async () => {
    const onChange = vi.fn();
    window.addEventListener("consent-change", onChange);
    render(<CookieConsentBanner />);

    const reject = await screen.findByRole("button", { name: "Reject all" });
    fireEvent.click(reject);

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Cookie preferences" }))
        .not.toBeInTheDocument();
    });
    expect(loadConsent()).toMatchObject({
      necessary: true,
      analytics: false,
      decided: true,
    });
    expect(onChange).toHaveBeenCalledOnce();
    window.removeEventListener("consent-change", onChange);
  });

  it("recovers safely from a corrupt stored preference", () => {
    window.localStorage.setItem("cookie_consent", "not-json");
    expect(loadConsent()).toEqual({
      necessary: true,
      analytics: false,
      decided: false,
    });
  });
});

describe("GuestBanner", () => {
  it("uses singular quota copy and links to registration", () => {
    render(<GuestBanner remaining={1} />);
    expect(screen.getByText(/Guest mode:/)).toHaveTextContent(
      "Guest mode: 1 query remaining today.",
    );
    expect(screen.getByRole("link", { name: /register for more queries/i }))
      .toHaveAttribute("href", "/register");
  });

  it("is absent for authenticated users", () => {
    const { container } = render(<GuestBanner remaining={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
