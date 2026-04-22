"use client";

/**
 * Form-submittable wrapper around FamilyMultiSelect.
 *
 * The Materials page is a server component that posts its filters
 * through a regular <form> (so refresh / bookmark / share all work
 * without client-side state). FamilyMultiSelect is a client
 * component holding an array. This shim bridges the two: state lives
 * in the client component, and a hidden <input name="family"> carries
 * a comma-joined slug list into the form submission.
 *
 * The backend's /materials endpoint accepts the same comma-separated
 * string the old single-slug filter used, so URL shape stays
 * backward-compatible ("?family=cuprate" still works).
 */
import { useState } from "react";
import { FamilyMultiSelect } from "./FamilyMultiSelect";

export function FamilyFilterField({ initial }: { initial: string }) {
  const [value, setValue] = useState<string[]>(
    initial ? initial.split(",").map((s) => s.trim()).filter(Boolean) : [],
  );
  return (
    <>
      <FamilyMultiSelect value={value} onChange={setValue} />
      {/* Hidden input keeps the form's GET submission shape unchanged:
          the server page reads searchParams.family as a comma-joined
          string and forwards it to the backend listMaterials call. */}
      <input type="hidden" name="family" value={value.join(",")} />
    </>
  );
}
