// API types - these match the backend schemas
// Note: All IDs are strings (nanoid) except BGG IDs which are numbers

// ============================================================================
// Enums
// ============================================================================

export type ResourceType = "rulebook" | "expansion" | "faq" | "errata" | "reference";
export type ResourceStatus = "ready" | "queued" | "processing" | "completed" | "failed";
export type ProcessingStage =
  | "ingest"
  | "vision"
  | "cleanup"
  | "metadata"
  | "segment"
  | "embed"
  | "finalize";
export type AttachmentType = "image";
export type DetectedType = "diagram" | "table" | "photo" | "icon" | "decorative";
export type QualityRating = "good" | "bad";
export type WorkflowStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type FragmentType = "text" | "image" | "table";

// ============================================================================
// Core Models
// ============================================================================

export interface User {
  id: string;
  email: string;
  name: string | null;
  is_admin: boolean;
}

export interface Game {
  id: string;
  name: string;
  slug: string;
  year: number | null;
  image_url: string | null;
  bgg_id: number | null;
  bgg_url: string | null;
  description: string | null;
  resource_count?: number;
}

export interface Resource {
  id: string;
  game_id: string;
  name: string;
  original_filename: string | null;
  url: string;
  description: string | null;
  status: ResourceStatus;
  resource_type: ResourceType;
  author: string | null;
  attribution_url: string | null;
  language: string | null;
  edition: string | null;
  is_official: boolean;
  processing_stage: ProcessingStage | null;
  page_count: number | null;
  image_count: number | null;
  word_count: number | null;
  segment_count?: number;
  fragment_count?: number;
}

export interface Attachment {
  id: string;
  game_id: string;
  resource_id: string;
  type: AttachmentType;
  mime_type: string;
  url: string;
  original_filename: string | null;
  page_number: number | null;
  bbox: Record<string, unknown> | null;
  width: number | null;
  height: number | null;
  caption: string | null;
  description: string | null;
  detected_type: DetectedType | null;
  is_good_quality: QualityRating | null;
  is_relevant: boolean | null;
  ocr_text: string | null;
}

export interface Fragment {
  id: string;
  game_id: string;
  resource_id: string;
  content: string;
  type: FragmentType;
  page_number: number | null;
  section: string | null;
  attachment_id: string | null;
}

export interface Segment {
  id: string;
  resource_id: string;
  game_id: string;
  title: string;
  hierarchy_path: string;
  level: number;
  order_index: number;
  content: string;
  page_start: number | null;
  page_end: number | null;
  word_count: number | null;
  char_count: number | null;
  parent_id: string | null;
}

export interface WorkflowRun {
  id: string;
  run_id: string;
  workflow_name: string;
  status: WorkflowStatus;
  started_at: string | null;
  completed_at: string | null;
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
  error: string | null;
  error_code: string | null;
  resource_id: string | null;
  attachment_id: string | null;
  game_id: string | null;
  extra_data: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  // Computed fields from backend
  progress_percent: number | null;
  stage_label: string | null;
  resource_name: string | null;
  retry_count: number;
  can_retry: boolean;
}

export interface BggGame {
  id: number; // BGG ID is a number, not nanoid
  name: string;
  year_published: number | null;
  min_players: number | null;
  max_players: number | null;
  playing_time: number | null;
  thumbnail_url: string | null;
  image_url: string | null;
  description: string | null;
  publishers: string[] | null;
  designers: string[] | null;
  categories: string[] | null;
  mechanics: string[] | null;
  cached_at: number;
}

// ============================================================================
// Auth Types
// ============================================================================

export interface LoginResponse {
  message: string;
  magic_link?: string; // Only in development
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

// ============================================================================
// Chat Types
// ============================================================================

export interface ToolCall {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  status: "running" | "completed";
  result?: unknown;
  durationMs?: number;
  startTime?: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCall[];
}

export interface Citation {
  resource_id: string;
  resource_name: string;
  page_number: number | null;
  section: string | null;
  relevance: string;
}

export interface ChatResponse {
  content: string;
  citations: Citation[];
  confidence: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  stream?: boolean;
}

// ============================================================================
// Search Types
// ============================================================================

export interface ImageMetadata {
  id: string;
  url: string;
  bbox: number[] | null;
  caption: string | null;
  description: string | null;
  detected_type: string | null;
  ocr_text: string | null;
  is_relevant: boolean | null;
}

export interface SearchResult {
  fragment_id: string;
  content: string;
  page_number: number | null;
  section: string | null;
  resource_id: string;
  resource_name: string;
  game_id: string;
  score: number;
  images: ImageMetadata[] | null;
  searchable_content: string | null;
}

export interface SearchResponse {
  results: SearchResult[];
  query: string;
  game_id: string | null;
  total: number;
}

// ============================================================================
// BGG Search Types
// ============================================================================

export interface BggSearchResult {
  id: number;
  name: string;
  year_published: number | null;
}

// ============================================================================
// Upload Types
// ============================================================================

export interface UploadResponse {
  resource: Resource;
  message: string;
}

export interface FileUploadResponse {
  url: string;
  blob_key: string;
  size: number;
  mime_type: string;
}

// ============================================================================
// Create/Update Types
// ============================================================================

export interface GameCreate {
  name: string;
  slug?: string;
  year?: number | null;
  image_url?: string | null;
  bgg_id?: number | null;
  bgg_url?: string | null;
  description?: string | null;
}

export interface GameUpdate {
  name?: string;
  slug?: string;
  year?: number | null;
  image_url?: string | null;
  bgg_id?: number | null;
  bgg_url?: string | null;
  description?: string | null;
}

export interface ResourceUpdate {
  name?: string;
  resource_type?: ResourceType;
  status?: ResourceStatus;
}

export interface AttachmentUpdate {
  description?: string | null;
  detected_type?: DetectedType | null;
  is_good_quality?: QualityRating | null;
}

// ============================================================================
// Reprocess Types
// ============================================================================

export interface ReprocessResponse {
  message: string;
  run_id: string;
}

// ============================================================================
// Error Types
// ============================================================================

export interface ErrorResponse {
  detail: string;
}

// ============================================================================
// Health Types
// ============================================================================

export interface HealthCheck {
  status: string;
}

export interface HealthCheckDb {
  status: string;
  database: string;
}
