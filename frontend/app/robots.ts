import type { MetadataRoute } from "next";
import { SITE_BASE_URL, SITE_ORIGIN } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/york-interview/",
          "/auth/",
          "/dashboard/",
          "/forgot-password",
          "/login",
          "/register",
          "/reset-password",
          "/verify",
        ],
      },
    ],
    sitemap: `${SITE_BASE_URL}/sitemap.xml`,
    host: SITE_ORIGIN,
  };
}
