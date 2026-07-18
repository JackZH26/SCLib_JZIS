import type { MetadataRoute } from "next";
import { SITE_BASE_URL, SITE_ORIGIN } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/sclib/",
        disallow: [
          "/sclib/auth/",
          "/sclib/dashboard/",
          "/sclib/forgot-password",
          "/sclib/login",
          "/sclib/register",
          "/sclib/reset-password",
          "/sclib/verify",
        ],
      },
    ],
    sitemap: `${SITE_BASE_URL}/sitemap.xml`,
    host: SITE_ORIGIN,
  };
}
