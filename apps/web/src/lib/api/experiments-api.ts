/**
 * API functions for Experiments.
 */

import type {
  Experiment,
  ExperimentListResponse,
  ExperimentCreateBody,
  ExperimentUpdateBody,
} from "../api-types";
import { request } from "./client";

// --- Experiments ---

export const getExperiments = () =>
  request<ExperimentListResponse>("/api/experiments");

export const getExperiment = (id: string) =>
  request<Experiment>(`/api/experiments/${id}`);

export const createExperiment = (body: ExperimentCreateBody) =>
  request<Experiment>("/api/experiments", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateExperiment = (id: string, body: ExperimentUpdateBody) =>
  request<Experiment>(`/api/experiments/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteExperiment = (id: string) =>
  request<void>(`/api/experiments/${id}`, { method: "DELETE" });
