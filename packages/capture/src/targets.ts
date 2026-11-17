import type { Locator, Page } from "playwright";
import type { Target } from "./steps";

export type LocatorSource = Pick<Page, "getByTestId" | "getByText" | "getByRole" | "locator">;

type RoleArg = Parameters<Page["getByRole"]>[0];

export function resolveTarget(page: LocatorSource, target: Target): Locator {
  if ("testId" in target) return page.getByTestId(target.testId);
  if ("css" in target) return page.locator(target.css);
  if ("role" in target) {
    return page.getByRole(target.role as RoleArg, {
      ...(target.name !== undefined ? { name: target.name } : {}),
      ...(target.exact !== undefined ? { exact: target.exact } : {}),
    });
  }
  return page.getByText(target.text, target.exact !== undefined ? { exact: target.exact } : {});
}

export function resolveOne(page: LocatorSource, target: Target): Locator {
  return resolveTarget(page, target).nth(target.nth ?? 0);
}
