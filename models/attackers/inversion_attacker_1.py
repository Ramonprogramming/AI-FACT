###############################################################################
# MIT License
#
# Copyright (c) 2020
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to conditions.
#
# Authors: Luuk Kaandorp, Ward Pennink, Ramon Dijkstra, Reinier Bekkenutte 
# Date Created: 2020-01-08
###############################################################################

"""
Model for inversion attacks
"""

# Adapted from https://amaarora.github.io/2020/09/13/unet.html

import argparse
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision

import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint

class Block(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(out_ch, out_ch, 3, padding=1)
        )
    
    def forward(self, x):
        return self.layers(x)


class Encoder(nn.Module):
    def __init__(self, chs=(6,64,128,256,512,1024)):
        super().__init__()
        self.enc_blocks = nn.ModuleList([Block(chs[i], chs[i+1]) for i in range(len(chs)-1)])
        self.pool = nn.MaxPool2d(2)
    
    def forward(self, x):
        ftrs = []
        for block in self.enc_blocks:
            x = block(x)
            ftrs.append(x)
            x = self.pool(x)
        return ftrs


class Decoder(nn.Module):
    def __init__(self, chs=(1024, 512, 256, 128, 64)):
        super().__init__()
        self.chs = chs
        self.upconvs = nn.ModuleList([nn.ConvTranspose2d(chs[i], chs[i+1], 2, 2) for i in range(len(chs)-1)])
        self.dec_blocks = nn.ModuleList([Block(chs[i], chs[i+1]) for i in range(len(chs)-1)])
        
    def forward(self, x, encoder_features):
        for i in range(len(self.chs)-1):
            x = self.upconvs[i](x)
            enc_ftrs = self.crop(encoder_features[i], x)
            x = torch.cat([x, enc_ftrs], dim=1)
            x = self.dec_blocks[i](x)
        return x
    
    def crop(self, enc_ftrs, x):
        _, _, H, W = x.shape
        enc_ftrs = torchvision.transforms.CenterCrop([H, W])(enc_ftrs)
        return enc_ftrs


class UNet(pl.LightningModule):
    def __init__(self, generator, encoding_layer, enc_chs=(6,64,128,256,512), dec_chs=(512, 256, 128, 64), num_classes=3, retain_dim=True, out_sz=(32,32), training=True, lr=3e-4):
        super().__init__()
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

        self.training = training
        self.upsample = nn.Upsample(size=(32,32))

        self.gan = generator
        print("SDKJHFSKLJFDLKSJ")
        print(self.gan)
        if self.gan is not None:
            self.gan.requires_grad = False
        self.change_channels = encoding_layer
        if self.change_channels is not None:
            self.change_channels.requires_grad = False
        #print(self.gan)
        #print(self.gan.encoding_layer)
        #print("sdflkjsdklfgjdfklgj")

        self.encoder = Encoder(enc_chs)
        self.decoder = Decoder(dec_chs)
        self.out_sz = out_sz
        self.head = nn.Conv2d(dec_chs[-1], num_classes, 1)
        self.retain_dim = retain_dim
        self.loss_fn = nn.MSELoss(reduction='mean')
        self.lr = lr
        


    def configure_optimizers(self):
        """
        Function to configure the optimizers
        """
        # initialize optimizer for the entire model
        model_optimizer = torch.optim.Adam(self.parameters(), lr=self.lr)
        
        # return the optimizer
        return model_optimizer

    def training_step(self, batch, optimizer_idx):
        """
        Inputs:
            image_batch - Input batch of images. Shape: [B, C, W, H]
                B - batch size
                C - channels per image
                W- image width
                H - image height
            training - Boolean value. Default = True
                True when training
                False when using in application
        Outputs:
			decoded_feature - Output batch of decoded real features. Shape: [B, C, W, H]
                B - batch size
                C - channels per feature
                W- feature width
                H - feature height
            discriminator_predictions - Predictions from the discriminator. Shape: [B * k, 1]
            labels - Real labels of the encoded features. Shape: [B * k, 1]
        """

        x, _ = batch

        with torch.no_grad():
            x2 = self.change_channels(x)


       # print(torch.max(x),torch.min(x))


        enc_ftrs = self.encoder(x2)
        out = self.decoder(enc_ftrs[::-1][0], enc_ftrs[::-1][1:])
        out = self.head(out)
        if self.retain_dim:
            out = F.interpolate(out, self.out_sz)
        loss = self.loss_fn(out, x)

        self.log("total/loss", loss)

        return loss

    def validation_step(self, batch, batch_idx):
        x, _ = batch

        with torch.no_grad():
            x2 = self.change_channels(x)


        enc_ftrs = self.encoder(x2)
        out = self.decoder(enc_ftrs[::-1][0], enc_ftrs[::-1][1:])
        out = self.head(out)
        if self.retain_dim:
            out = F.interpolate(out, self.out_sz)

        loss = self.loss_fn(out, x)

        self.log("val/loss", loss)
        return loss


    def test_step(self, batch, batch_idx):
        x, _ = batch

        #with torch.no_grad():
       #     x2 = self.change_channels(x)

        _, encoded_x, thetas, _, _ = self.gan(x)
        #encoded_x = self.gan.generator(x)


        hoi = nn.ConvTranspose2d(6,3,1).to(self.device)
        encoded_x = hoi(encoded_x)
        encoded_x = self.upsample(encoded_x)

        enc_ftrs = self.encoder(encoded_x)
        out = self.decoder(enc_ftrs[::-1][0], enc_ftrs[::-1][1:])
        out = self.head(out)
        if self.retain_dim:
            out = F.interpolate(out, self.out_sz)

        loss = self.loss_fn(out, x)

        self.log("total/reconstruction_error", loss)
        
        return loss
