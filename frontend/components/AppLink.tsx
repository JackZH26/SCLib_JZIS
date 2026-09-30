"use client";

import NextLink from "next/link";
import type { ComponentProps } from "react";

/** Data-backed destinations load on navigation, not for every visible citation. */
export default function AppLink(props: ComponentProps<typeof NextLink>) {
  return <NextLink {...props} prefetch={false} />;
}
