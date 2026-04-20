#!/usr/bin/env node
/**
 * Standalone CLI entry for the onboarding wizard (R1 AC1 + AC2).
 * Invokable directly by the user and argv-less by onboarding-backend R4.
 */

import { runWizard } from "./index";

runWizard().then(
  (result) => process.exit(result.exitCode),
  (err) => {
    console.error("wizard failed:", err);
    process.exit(1);
  },
);
