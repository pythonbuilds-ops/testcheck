#!/usr/bin/env python3
"""
greet.py — use the trained greeting model

Usage:
    python greet.py              # uses current system time automatically
    python greet.py "23:45"      # specific time
"""

import sys
import math
import datetime
import torch
import torch.nn as nn

DEVICE = "cpu"
MODEL_PATH = "greeting_net.pt"

SOS = "\x02"
EOS = "\x03"
PAD = "\x00"


class GreetingNet(nn.Module):
    def __init__(self, vocab_size, embed_dim=64, hidden_dim=256, num_layers=2):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.time_proj = nn.Sequential(
            nn.Linear(2, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim * 2 * num_layers),
        )
        self.embed = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm  = nn.LSTM(embed_dim, hidden_dim, num_layers=num_layers,
                             batch_first=True, dropout=0.3)
        self.fc    = nn.Linear(hidden_dim, vocab_size)

    def _encode_time(self, hours):
        a    = 2 * math.pi * hours / 24.0
        feat = torch.stack([torch.sin(a), torch.cos(a)], dim=-1)
        out  = self.time_proj(feat)
        out  = out.view(-1, self.num_layers, 2, self.hidden_dim)
        h0   = out[:, :, 0, :].permute(1, 0, 2).contiguous()
        c0   = out[:, :, 1, :].permute(1, 0, 2).contiguous()
        return h0, c0

    @torch.no_grad()
    def generate(self, hour_float, c2i, i2c,
                 max_len=80, temperature=0.75, top_k=5):
        self.eval()
        hours     = torch.tensor([hour_float], dtype=torch.float32)
        h0, c0    = self._encode_time(hours)
        token     = torch.tensor([[c2i[SOS]]])
        result    = []
        for _ in range(max_len):
            emb            = self.embed(token)
            out, (h0, c0)  = self.lstm(emb, (h0, c0))
            logits         = self.fc(out[:, -1, :]) / temperature
            topv, topi     = logits.topk(top_k)
            probs          = torch.softmax(topv, dim=-1)
            chosen         = topi[0, torch.multinomial(probs[0], 1)]
            ch             = i2c[chosen.item()]
            if ch == EOS:
                break
            result.append(ch)
            token = chosen.view(1, 1)
        return "".join(result)


def load_model():
    ckpt       = torch.load(MODEL_PATH, map_location=DEVICE, weights_only=False)
    vocab_size = len(ckpt["vocab"])
    model      = GreetingNet(vocab_size)
    model.load_state_dict(ckpt["model_state"])
    return model, ckpt["c2i"], ckpt["i2c"]


def parse_time(time_str):
    h, m = (int(x) for x in time_str.split(":"))
    return h + m / 60.0


def main():
    model, c2i, i2c = load_model()

    if len(sys.argv) > 1:
        time_str   = sys.argv[1]
        hour_float = parse_time(time_str)
    else:
        now        = datetime.datetime.now()
        time_str   = now.strftime("%H:%M")
        hour_float = now.hour + now.minute / 60.0

    phrase = model.generate(hour_float, c2i, i2c)
    print(f"{phrase}")


if __name__ == "__main__":
    main()
