// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Re-export canonical derivation logic from src/derive.ts.
 * Existing tests import from this path — this re-export maintains compatibility.
 */
export { derive, resetDerivationState } from "../../src/derive.js";
