"""The layers of the reading comprehension architecture
   Used by models.py.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import urnn
import goru
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
from util import masked_softmax


class Embedding(nn.Module):
    """Embedding layer used by BiDAF, word embeddings.

    """
    def __init__(self, word_vectors, hidden_size, drop_prob):
        super(Embedding, self).__init__()
        self.drop_prob = drop_prob
        self.embed = nn.Embedding.from_pretrained(word_vectors)
        self.proj = nn.Linear(word_vectors.size(1), hidden_size, bias=False)
        self.hwy = HighwayEncoder(2, hidden_size)

    def forward(self, x):
        emb = self.embed(x)   # (batch_size, seq_len, embed_size)
        emb = F.dropout(emb, self.drop_prob, self.training)
        emb = self.proj(emb)  # (batch_size, seq_len, hidden_size)
        emb = self.hwy(emb)   # (batch_size, seq_len, hidden_size)

        return emb

class EmbeddingChar(nn.Module):
    """
    Embedding layer word +  character-level component.
    """
    def __init__(self, word_vectors, char_vectors, hidden_size, drop_prob):
        super(EmbeddingChar, self).__init__()
        self.drop_prob = drop_prob
        # word embedding
        self.word_emb_size = word_vectors.size(1)
        self.embed = nn.Embedding.from_pretrained(word_vectors)
        # character embedding
        self.char_emb_size = char_vectors.size(1)
        self.char_embed = nn.Embedding.from_pretrained(char_vectors, freeze=False)
        # CNN layer
        n_filters = self.word_emb_size
        kernel_size = 5
        self.cnn = CNN(self.char_emb_size, n_filters, k=kernel_size)
        self.proj = nn.Linear(2 * self.word_emb_size, hidden_size, bias=False)
        self.hwy = HighwayEncoder(2, hidden_size)

    def forward(self, x_word, x_char):
        # char embedding
        _, seq_len, max_word_len = x_char.size()
        # reshape to a batch of characters word-sequence
        x_char = x_char.view(-1, max_word_len)  # (b = batch_size*seq_len, max_word_len)
        # character-level embedding
        emb_char = self.char_embed(x_char)  # (b, max_word_len, char_emb_size)
        # transpose to match the CNN shape requirements
        emb_char = emb_char.transpose(1, 2)  # (b, n_channel_in = char_emb_size, max_word_len)
        # pass through cnn
        emb_char = self.cnn(emb_char)  # (b, n_channel_out = word_emb_size)
        # reshape to a batch of sentences of words embeddings
        emb_char = emb_char.view(-1, seq_len, self.word_emb_size)  # (batch_size, seq_len, word_emb_size)
        # word embedding
        emb_word = self.embed(x_word)  # (batch_size, seq_len, word_emb_size)
        # concatenate the char and word embeddings
        emb = torch.cat((emb_word, emb_char), 2)  # (batch_size, seq_len, 2*word_emb_size)
        emb = F.dropout(emb, self.drop_prob, self.training)
        emb = self.proj(emb)  # (batch_size, seq_len, hidden_size)
        emb = self.hwy(emb)  # (batch_size, seq_len, hidden_size)
        return emb


class Embedding_Char(nn.Module):
    """Embedding layer  with the word + character-level component.
    """

    def __init__(self, word_vectors, char_vectors, hidden_size, drop_prob):
        super(Embedding_Char, self).__init__()
        self.drop_prob = drop_prob

        # word embedding
        self.word_emb_size = word_vectors.size(1)
        self.embed = nn.Embedding.from_pretrained(word_vectors)

        # character embedding
        self.char_emb_size = char_vectors.size(1)
        self.char_embed = nn.Embedding.from_pretrained(char_vectors, freeze=False)

        # CNN layer
        n_filters = self.word_emb_size
        kernel_size = 5
        self.cnn = CNN(self.char_emb_size, n_filters, k=kernel_size)

        self.proj = nn.Linear(2 * self.word_emb_size, hidden_size, bias=False)
        self.hwy = HighwayEncoder(2, hidden_size)

    def forward(self, x_word, x_char):
        # char embedding
        _, seq_len, max_word_len = x_char.size()
        # reshape to a batch of characters word-sequence
        x_char = x_char.view(-1, max_word_len)  # (b = batch_size*seq_len, max_word_len)
        # character-level embedding
        emb_char = self.char_embed(x_char)  # (b, max_word_len, char_emb_size)
        # transpose to match the CNN shape requirements
        emb_char = emb_char.transpose(1, 2)  # (b, n_channel_in = char_emb_size, max_word_len)
        # pass through cnn
        emb_char = self.cnn(emb_char)  # (b, n_channel_out = word_emb_size)
        # reshape to a batch of sentences of words embeddings
        emb_char = emb_char.view(-1, seq_len, self.word_emb_size)  # (batch_size, seq_len, word_emb_size)

        # word embedding
        emb_word = self.embed(x_word)  # (batch_size, seq_len, word_emb_size)

        # concatenate the char and word embeddings
        emb = torch.cat((emb_word, emb_char), 2)  # (batch_size, seq_len, 2*word_emb_size)

        emb = F.dropout(emb, self.drop_prob, self.training)
        emb = self.proj(emb)  # (batch_size, seq_len, hidden_size)
        emb = self.hwy(emb)  # (batch_size, seq_len, hidden_size)

        return emb


class CNN(nn.Module):
    def __init__(self, char_emb_size, f, k=5):
        super(CNN, self).__init__()
        self.conv1D = nn.Conv1d(char_emb_size, f, k, bias=True)

    def forward(self, X_reshaped):
        X_conv = self.conv1D(X_reshaped)  # (b, f, max_word_length - k +1)

        # pooling layer to collapse the last dimension
        X_conv_out, _ = torch.max(F.relu(X_conv), dim=2)  # (b, f)

        return X_conv_out


class HighwayEncoder(nn.Module):
    """Encode an input sequence using a highway network.
    """
    def __init__(self, num_layers, hidden_size):
        super(HighwayEncoder, self).__init__()
        self.transforms = nn.ModuleList([nn.Linear(hidden_size, hidden_size)
                                         for _ in range(num_layers)])
        self.gates = nn.ModuleList([nn.Linear(hidden_size, hidden_size)
                                    for _ in range(num_layers)])

    def forward(self, x):
        for gate, transform in zip(self.gates, self.transforms):
            # Shapes of g, t, and x are all (batch_size, seq_len, hidden_size)
            g = torch.sigmoid(gate(x))
            t = F.relu(transform(x))
            x = g * t + (1 - g) * x

        return x


class RNNEncoder(nn.Module):
    """ encoding a sequence using a bidirectional RNN.
    """
    def __init__(self,
                 input_size,
                 hidden_size,
                 num_layers,
                 rnn_type,
                 drop_prob=0.):
        super(RNNEncoder, self).__init__()
        self.drop_prob = drop_prob
        if rnn_type == 'LSTM':
            self.rnn = nn.LSTM(input_size, hidden_size, num_layers,
                           batch_first=True,
                           bidirectional=True,
                           dropout=drop_prob if num_layers > 1 else 0.)
        elif rnn_type == 'RNN':
            self.rnn = nn.RNN(input_size, hidden_size, num_layers,
                           batch_first=True,
                           bidirectional=True,
                           dropout=drop_prob if num_layers > 1 else 0.)
        elif rnn_type == 'GRU':
            self.rnn = nn.GRU(input_size, hidden_size, num_layers,
                           batch_first=True,
                           bidirectional=True,
                           dropout=drop_prob if num_layers > 1 else 0.)
        elif rnn_type == 'URNN':
            self.rnn = urnn.EURNNCell(input_size, hidden_size,
                                      capacity=2)
        elif rnn_type == 'GORU':
            self.rnn = goru.GORUCell(input_size, hidden_size,
                               capacity=2)

    def forward(self, x, lengths):
        # Save original padded length for use by pad_packed_sequence
        orig_len = x.size(1)

        # Sort by length and pack sequence for RNN
        lengths, sort_idx = lengths.sort(0, descending=True)
        x = x[sort_idx]     # (batch_size, seq_len, input_size)
        x = pack_padded_sequence(x, lengths, batch_first=True)

        # Apply RNN
        x, _ = self.rnn(x)  # (batch_size, seq_len, 2 * hidden_size)

        # Unpack and reverse sort
        x, _ = pad_packed_sequence(x, batch_first=True, total_length=orig_len)
        _, unsort_idx = sort_idx.sort(0)
        x = x[unsort_idx]   # (batch_size, seq_len, 2 * hidden_size)

        # Apply dropout (RNN applies dropout after all but the last layer)
        x = F.dropout(x, self.drop_prob, self.training)

        return x


class BiDAFAttention(nn.Module):
    """Bidirectional attention flow layer  used by BiDAF paper.
    """
    def __init__(self, hidden_size, drop_prob=0.1):
        super(BiDAFAttention, self).__init__()
        self.drop_prob = drop_prob
        self.c_weight = nn.Parameter(torch.zeros(hidden_size, 1))
        self.q_weight = nn.Parameter(torch.zeros(hidden_size, 1))
        self.cq_weight = nn.Parameter(torch.zeros(1, 1, hidden_size))
        for weight in (self.c_weight, self.q_weight, self.cq_weight):
            nn.init.xavier_uniform_(weight)
        self.bias = nn.Parameter(torch.zeros(1))

    def forward(self, c, q, c_mask, q_mask):
        batch_size, c_len, _ = c.size()
        q_len = q.size(1)
        s = self.get_similarity_matrix(c, q)        # (batch_size, c_len, q_len)
        c_mask = c_mask.view(batch_size, c_len, 1)  # (batch_size, c_len, 1)
        q_mask = q_mask.view(batch_size, 1, q_len)  # (batch_size, 1, q_len)
        s1 = masked_softmax(s, q_mask, dim=2)       # (batch_size, c_len, q_len)
        s2 = masked_softmax(s, c_mask, dim=1)       # (batch_size, c_len, q_len)

        # (bs, c_len, q_len) x (bs, q_len, hid_size) => (bs, c_len, hid_size)
        a = torch.bmm(s1, q)
        # (bs, c_len, c_len) x (bs, c_len, hid_size) => (bs, c_len, hid_size)
        b = torch.bmm(torch.bmm(s1, s2.transpose(1, 2)), c)

        x = torch.cat([c, a, c * a, c * b], dim=2)  # (bs, c_len, 4 * hid_size)

        return x

    def get_similarity_matrix(self, c, q):
        """Get the "similarity matrix" between context and query
        """
        c_len, q_len = c.size(1), q.size(1)
        c = F.dropout(c, self.drop_prob, self.training)  # (bs, c_len, hid_size)
        q = F.dropout(q, self.drop_prob, self.training)  # (bs, q_len, hid_size)

        # Shapes: (batch_size, c_len, q_len)
        s0 = torch.matmul(c, self.c_weight).expand([-1, -1, q_len])
        s1 = torch.matmul(q, self.q_weight).transpose(1, 2)\
                                           .expand([-1, c_len, -1])
        s2 = torch.matmul(c * self.cq_weight, q.transpose(1, 2))
        s = s0 + s1 + s2 + self.bias

        return s


class BiDAFOutput(nn.Module):
    """Output layer

    Linear transformation of the attention and modeling
    outputs, then takes the softmax of the result to get the start pointer.
    A bidirectional LSTM is then applied the modeling output to produce `mod_2`.
    A second linear+softmax of the attention output and `mod_2` is used
    to get the end pointer.

    """
    def __init__(self, hidden_size, drop_prob):
        super(BiDAFOutput, self).__init__()
        self.att_linear_1 = nn.Linear(8 * hidden_size, 1)
        self.mod_linear_1 = nn.Linear(2 * hidden_size, 1)

        self.rnn = RNNEncoder(input_size=2 * hidden_size,
                              hidden_size=hidden_size,
                              num_layers=1,
                              rnn_type='LSTM',
                              drop_prob=drop_prob)

        self.att_linear_2 = nn.Linear(8 * hidden_size, 1)
        self.mod_linear_2 = nn.Linear(2 * hidden_size, 1)

    def forward(self, att, mod, mask):
        # Shapes: (batch_size, seq_len, 1)
        logits_1 = self.att_linear_1(att) + self.mod_linear_1(mod)
        mod_2 = self.rnn(mod, mask.sum(-1))
        logits_2 = self.att_linear_2(att) + self.mod_linear_2(mod_2)

        # Shapes: (batch_size, seq_len)
        log_p1 = masked_softmax(logits_1.squeeze(), mask, log_softmax=True)
        log_p2 = masked_softmax(logits_2.squeeze(), mask, log_softmax=True)

        return log_p1, log_p2

