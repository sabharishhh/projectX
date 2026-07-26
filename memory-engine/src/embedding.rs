// bge-base-en via candle's native BERT. BGE convention: CLS-token pooling
// + L2 normalize (not mean pooling). Queries get an instruction prefix;
// stored memory units do not — mixing this up silently degrades relevance.

use anyhow::Result;
use candle_core::{Device, IndexOp, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::bert::{BertModel, Config as BertConfig, DTYPE};
use hf_hub::api::sync::Api;
use tokenizers::Tokenizer;

const MODEL_ID: &str = "BAAI/bge-base-en-v1.5";
const QUERY_INSTRUCTION: &str = "Represent this sentence for searching relevant passages: ";

pub struct Embedder {
    model: BertModel,
    tokenizer: Tokenizer,
    device: Device,
}

impl Embedder {
    /// Downloads bge-base-en on first run (hf-hub caches locally after that).
    pub fn load() -> Result<Self> {
        let device = Device::Cpu;
        let api = Api::new()?;
        let repo = api.model(MODEL_ID.to_string());

        let config: BertConfig = serde_json::from_str(
            &std::fs::read_to_string(repo.get("config.json")?)?,
        )?;
        let tokenizer = Tokenizer::from_file(repo.get("tokenizer.json")?)
            .map_err(|e| anyhow::anyhow!("tokenizer load: {e}"))?;
        let vb = unsafe {
            VarBuilder::from_mmaped_safetensors(&[repo.get("model.safetensors")?], DTYPE, &device)?
        };

        Ok(Self { model: BertModel::load(vb, &config)?, tokenizer, device })
    }

    /// Memory unit content — no instruction prefix.
    pub fn embed_document(&self, text: &str) -> Result<Vec<f32>> {
        self.embed(text)
    }

    /// Query text — needs the retrieval instruction prefix, or scores skew
    /// against every document (BGE was trained asymmetrically).
    pub fn embed_query(&self, text: &str) -> Result<Vec<f32>> {
        self.embed(&format!("{QUERY_INSTRUCTION}{text}"))
    }

    fn embed(&self, text: &str) -> Result<Vec<f32>> {
        let enc = self.tokenizer.encode(text, true)
            .map_err(|e| anyhow::anyhow!("tokenize: {e}"))?;
        let ids = Tensor::new(enc.get_ids(), &self.device)?.unsqueeze(0)?;
        let mask = Tensor::new(enc.get_attention_mask(), &self.device)?.unsqueeze(0)?;
        let token_type_ids = ids.zeros_like()?;

        let out = self.model.forward(&ids, &token_type_ids, Some(&mask))?;
        let cls = out.i((.., 0, ..))?; // CLS token, not mean-pooled
        let norm = cls.sqr()?.sum_keepdim(1)?.sqrt()?;
        Ok(cls.broadcast_div(&norm)?.squeeze(0)?.to_vec1::<f32>()?)
    }
}

/// Vectors are already L2-normalized, so cosine similarity is just a dot product.
pub fn cosine_sim(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}