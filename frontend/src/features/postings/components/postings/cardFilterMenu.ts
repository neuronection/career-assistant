/**
 * The posting-card entity menu's filter half (plan 188): map a card value
 * (skill key, org name, spec enum) onto the URL-driven explore Filters and
 * back. Pure functions — no React, no IO — so the state mapping is
 * unit-testable and Explore owns only the patch + feedback wiring.
 */

import type { Filters } from "@/features/catalog/exploreParams";
import type { TriStateMode } from "@/components/filters/filterBits";

export type CardFilterAxis =
  | "skills"
  | "orgs"
  | "remotePolicy"
  | "seniority"
  | "contract";

export type CardFilterMode = TriStateMode;

export interface CardFilterTarget {
  axis: CardFilterAxis;
  value: string;
  label: string;
  /** Where the navigation group sends the user (skill/company page). */
  pageTo?: string;
}

export interface CardFilterApi {
  stateOf(axis: CardFilterAxis, value: string): "include" | "exclude" | null;
  apply(target: CardFilterTarget, mode: CardFilterMode): void;
}

interface FilterPair {
  include: string[];
  exclude: string[];
}

const pairOf = (filters: Filters, axis: CardFilterAxis): FilterPair => {
  switch (axis) {
    case "skills":
      return {
        include: filters.skills.map((skill) => skill.key),
        exclude: filters.skillsExclude,
      };
    case "orgs":
      return { include: filters.orgs, exclude: filters.orgsExclude };
    case "remotePolicy":
      return {
        include: filters.remotePolicy,
        exclude: filters.remotePolicyExclude,
      };
    case "seniority":
      return { include: filters.seniority, exclude: filters.seniorityExclude };
    case "contract":
      return { include: filters.contract, exclude: filters.contractExclude };
  }
};

export function filterStateOf(
  filters: Filters,
  axis: CardFilterAxis,
  value: string,
): "include" | "exclude" | null {
  const { include, exclude } = pairOf(filters, axis);
  if (include.includes(value)) return "include";
  if (exclude.includes(value)) return "exclude";
  return null;
}

/**
 * The next `patch()` update for one card value. The include side of the
 * skills axis is `{key, level}` objects, so the target key is edited in
 * place (level preserved) instead of round-tripping through string lists.
 */
export function applyCardFilter(
  filters: Filters,
  target: CardFilterTarget,
  mode: CardFilterMode,
): Partial<Filters> {
  const { axis, value } = target;
  if (axis === "skills") {
    const include = filters.skills.some((skill) => skill.key === value);
    switch (mode) {
      case "include":
        return {
          skills: include
            ? filters.skills
            : [...filters.skills, { key: value, level: null }],
          skillsExclude: filters.skillsExclude.filter((v) => v !== value),
        };
      case "exclude":
        return {
          skills: filters.skills.filter((skill) => skill.key !== value),
          skillsExclude: filters.skillsExclude.includes(value)
            ? filters.skillsExclude
            : [...filters.skillsExclude, value],
        };
      case "clear":
        return {
          skills: filters.skills.filter((skill) => skill.key !== value),
          skillsExclude: filters.skillsExclude.filter((v) => v !== value),
        };
    }
  }
  const { include, exclude } = pairOf(filters, axis);
  const drop = (values: string[]) => values.filter((v) => v !== value);
  const add = (values: string[]) =>
    values.includes(value) ? values : [...values, value];
  switch (mode) {
    case "include":
      return buildAxisPatch(axis, add(include), drop(exclude));
    case "exclude":
      return buildAxisPatch(axis, drop(include), add(exclude));
    case "clear":
      return buildAxisPatch(axis, drop(include), drop(exclude));
  }
}

function buildAxisPatch(
  axis: Exclude<CardFilterAxis, "skills">,
  include: string[],
  exclude: string[],
): Partial<Filters> {
  switch (axis) {
    case "orgs":
      return { orgs: include, orgsExclude: exclude };
    case "remotePolicy":
      return { remotePolicy: include, remotePolicyExclude: exclude };
    case "seniority":
      return { seniority: include, seniorityExclude: exclude };
    case "contract":
      return { contract: include, contractExclude: exclude };
  }
}
