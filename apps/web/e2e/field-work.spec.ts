import { expect, test, type Page } from "@playwright/test";

const SUPERVISOR = {
  email: "supervisor@alpha-hospital.test",
  password: "SupervisorDev123!",
};
const WORKER = {
  email: "worker@alpha-hospital.test",
  password: "WorkerDev123!",
};

async function login(page: Page, user: { email: string; password: string }) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
}

async function sendPending(page: Page) {
  await page.getByRole("button", { name: "Send pending" }).click();
  await expect(page.getByTestId("sync-msg")).toBeVisible({ timeout: 20_000 });
}

async function refreshServer(page: Page) {
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByTestId("refresh-msg")).toBeVisible({ timeout: 20_000 });
}

test.describe("Elio field work E2E", () => {
  test("login rejects bad password", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Email").fill(WORKER.email);
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("login-error")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("supervisor creates work, assigns worker; worker accepts and starts", async ({
    page,
    context,
  }) => {
    await login(page, SUPERVISOR);

    // Create from facility inspection template
    await page.getByLabel("Template").selectOption("facility_inspection");
    const title = `E2E inspection ${Date.now()}`;
    await page.getByLabel("Title").fill(title);
    await page.getByRole("button", { name: "Create work" }).click();
    await expect(page.getByTestId("work-board-msg")).toBeVisible();

    await sendPending(page);
    await refreshServer(page);

    // Select created item in queue
    const queueItem = page.locator(".work-link", { hasText: title });
    await expect(queueItem).toBeVisible({ timeout: 15_000 });
    await queueItem.click();

    // Release
    await page.getByRole("button", { name: "Release", exact: true }).click();
    await expect(page.getByTestId("work-board-msg")).toContainText("Release", {
      timeout: 15_000,
    });
    await sendPending(page);

    // Operations: assign
    await page.getByRole("button", { name: "Operations" }).click();
    await expect(page.getByTestId("ops-pane")).toBeVisible();
    await page.getByTestId("ops-pane").getByRole("button", { name: "Refresh" }).click();
    await expect(page.getByTestId("ops-pane")).toBeVisible({ timeout: 15_000 });

    const opsRow = page.locator("tr", { hasText: title });
    await expect(opsRow).toBeVisible({ timeout: 15_000 });
    await opsRow.click();

    // Assign select — demo worker
    const assignSelect = page.locator("aside select").first();
    await assignSelect.selectOption({ label: "Demo Worker" });
    await opsRow.getByRole("button", { name: "Assign", exact: true }).click();
    await expect(page.getByTestId("ops-msg")).toContainText("Assignment", {
      timeout: 15_000,
    });

    await signOut(page);

    // Worker path
    await login(page, WORKER);
    await refreshServer(page);

    const workerItem = page.locator(".work-link", { hasText: title });
    await expect(workerItem).toBeVisible({ timeout: 15_000 });
    await workerItem.click();

    await expect(page.getByTestId("accept-job")).toBeVisible();
    await page.getByTestId("accept-job").click();
    await expect(page.getByTestId("field-msg")).toContainText("Accept", {
      timeout: 15_000,
    });
    await sendPending(page);

    await page.getByTestId("start-job").click();
    await expect(page.getByTestId("field-msg")).toContainText("Start", {
      timeout: 15_000,
    });
    await sendPending(page);

    // Guided checklist visible after start
    await expect(page.getByTestId("guided-steps")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("next-action")).toBeVisible();

    await context.close();
  });

  test("worker raises exception without submit loophole", async ({ page }) => {
    await login(page, SUPERVISOR);
    const title = `E2E blocked ${Date.now()}`;
    await page.getByLabel("Template").selectOption("facility_inspection");
    await page.getByLabel("Title").fill(title);
    await page.getByRole("button", { name: "Create work" }).click();
    await sendPending(page);
    await refreshServer(page);

    const queueItem = page.locator(".work-link", { hasText: title });
    await queueItem.click();
    await page.getByRole("button", { name: "Release", exact: true }).click();
    await sendPending(page);

    await page.getByRole("button", { name: "Operations" }).click();
    await page.getByTestId("ops-pane").getByRole("button", { name: "Refresh" }).click();
    const opsRow = page.locator("tr", { hasText: title });
    await expect(opsRow).toBeVisible({ timeout: 15_000 });
    await opsRow.click();
    await page.locator("aside select").first().selectOption({ label: "Demo Worker" });
    await opsRow.getByRole("button", { name: "Assign", exact: true }).click();
    await expect(page.getByTestId("ops-msg")).toContainText("Assignment");

    await signOut(page);
    await login(page, WORKER);
    await refreshServer(page);
    await page.locator(".work-link", { hasText: title }).click();
    await page.getByTestId("accept-job").click();
    await sendPending(page);
    await page.getByTestId("start-job").click();
    await sendPending(page);

    // Guided exception
    await expect(page.getByTestId("toggle-exception")).toBeVisible();
    await page.getByTestId("toggle-exception").click();
    await expect(page.getByTestId("exception-box")).toBeVisible();
    await page.getByLabel("Situation").selectOption("no_access");
    await page.getByLabel("Short note for your supervisor").fill("Gate locked, no guard");
    await page.getByRole("button", { name: "Report blocked" }).click();
    await expect(page.getByTestId("field-msg")).toContainText("blocked", {
      timeout: 15_000,
    });
    await sendPending(page);

    // Status should become blocked after refresh
    await refreshServer(page);
    await page.locator(".work-link", { hasText: title }).click();
    await expect(page.getByTestId("worker-exceptions")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Site unavailable", { exact: false })).toBeVisible();

    // Submit with exception outcome available when blocked
    await expect(page.getByTestId("submit-job")).toBeVisible();
  });

  test("sign out ends session", async ({ page }) => {
    await login(page, SUPERVISOR);
    await signOut(page);
    await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  });
});
