// memory-engine/src/reranker.rs
// bge-reranker-v2-m3 (XLM-RoBERTa-large cross-encoder) via candle's native
// XLMRobertaForSequenceClassification. Scores (query, document) pairs
// jointly — this is what catches "Robert Downey Jr specifically," not just
// "something actor-related," the way dense/BM25 structurally can't.

use anyhow::Result;
use candle_core::{DType, Device, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::xlm_roberta::{Config, XLMRobertaForSequenceClassification};
use hf_hub::api::sync::Api;
use tokenizers::Tokenizer;

const MODEL_ID: &str = "BAAI/bge-reranker-v2-m3";

pub struct Reranker {
    model: XLMRobertaForSequenceClassification,
    tokenizer: Tokenizer,
    device: Device,
}

impl Reranker {
    pub fn load() -> Result<Self> {
        let device = Device::Cpu;
        let api = Api::new()?;
        let repo = api.model(MODEL_ID.to_string());

        let config: Config = serde_json::from_str(
            &std::fs::read_to_string(repo.get("config.json")?)?,
        )?;
        let tokenizer = Tokenizer::from_file(repo.get("tokenizer.json")?)
            .map_err(|e| anyhow::anyhow!("tokenizer load: {e}"))?;
        let vb = unsafe {
            VarBuilder::from_mmaped_safetensors(&[repo.get("model.safetensors")?], DType::F32, &device)?
        };

        // num_labels = 1 — a reranker outputs one relevance logit, not a
        // class distribution.
        let model = XLMRobertaForSequenceClassification::new(1, &config, vb)?;
        Ok(Self { model, tokenizer, device })
    }

    /// Scores each (query, candidate) pair independently — real joint
    /// cross-attention per pair, not a batched vector comparison. Meant to
    /// run on a small k (16), not the whole store.
    pub fn rerank(&self, query: &str, candidates: &[&str]) -> Result<Vec<f32>> {
        candidates.iter().map(|doc| self.score_pair(query, doc)).collect()
    }

    fn score_pair(&self, query: &str, document: &str) -> Result<f32> {
        let enc = self
            .tokenizer
            .encode((query, document), true)
            .map_err(|e| anyhow::anyhow!("tokenize: {e}"))?;

        let ids = Tensor::new(enc.get_ids(), &self.device)?.unsqueeze(0)?;
        let mask = Tensor::new(enc.get_attention_mask(), &self.device)?
            .to_dtype(DType::F32)?
            .unsqueeze(0)?;
        let token_type_ids = ids.zeros_like()?;

        let logits = self.model.forward(&ids, &mask, &token_type_ids)?;
        let logit: f32 = logits.get(0)?.get(0)?.to_scalar()?;
        Ok(1.0 / (1.0 + (-logit).exp())) // sigmoid — BGE's own docs map score to [0,1] this way
    }
}