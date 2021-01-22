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
Main training file
"""

import argparse
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning.callbacks.early_stopping import EarlyStopping

# import models
from models.attackers.inversion_attacker import *

# import dataloaders
from dataloaders.cifar10_loader import load_data as load_cifar10_data
from dataloaders.cifar100_loader import load_data as load_cifar100_data
from dataloaders.celeba_loader import load_data as load_celeba_data

from os import listdir
from os.path import isfile, join

# initialize our model dictionary
model_dict = {}
model_dict['UNet'] = UNet
# model_dict['Inference'] = Inference

# initialize our dataset dictionary
dataset_dict = {}
dataset_dict['CIFAR-10'] = load_cifar10_data
dataset_dict['CIFAR-100'] = load_cifar100_data
dataset_dict['CelebA'] = load_celeba_data

def train_model(args):
    """
    Function for training and testing a model.
    
    Inputs:
        args - Namespace object from the argument parser
    """
    
    # DEBUG
    torch.autograd.set_detect_anomaly(True)
    
    # make folder for the Lightning logs
    os.makedirs(args.log_dir, exist_ok=True)
    
    # load the data from the dataloader  
    classes, trainloader, valloader, testloader = load_data_fn(
        args.dataset, args.batch_size, args.num_workers
    )

    early_stop_callback = EarlyStopping(
        monitor='val/loss',
        min_delta=0.005,
        patience=3,
        verbose=False,
        mode='min'
    )

    # initialize the Lightning trainer
    trainer = pl.Trainer(default_root_dir=args.log_dir,
                        checkpoint_callback=ModelCheckpoint(
                            save_weights_only=True
                        ),
                        gpus=1 if torch.cuda.is_available() else 0,
                        max_epochs=args.epochs,
                        progress_bar_refresh_rate=1 if args.progress_bar else 0,
                        callbacks=[early_stop_callback])
    trainer.logger._default_hp_metric = None

    # seed for reproducability
    pl.seed_everything(args.seed)
    
    # initialize the model
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    num_classes = 3

    # show the progress bar if enabled
    if not args.progress_bar:
        print("\nThe progress bar has been surpressed. For updates on the training progress, " + \
              "check the TensorBoard file at " + trainer.logger.log_dir + ". If you " + \
              "want to see the progress bar, use the argparse option \"progress_bar\".\n")

    # Depending on model
    model = initialize_model(args.model, num_classes, args.lr, args.k)

    if args.load_dict:
        model = model.load_from_checkpoint(
            checkpoint_path="attacker_logs\lightning_logs\\version_26\checkpoints\epoch=17.ckpt",
            hparams_file="attacker_logs\lightning_logs\\version_26\hparams.yml",
            # map_location=None
        )
        # model.load_state_dict(torch.load(args.load_dict))
    else:
        # train the model
        trainer.fit(model, trainloader, valloader)

    # save the model    
    path = 'saved_models/'
    allfiles = [f for f in listdir(path) if isfile(join(path, f))]
    torch.save(model.state_dict(), 'saved_models/inference_attack_model_v' + str(len(allfiles)) + '.pt')

    # test the model
    trainer.test(model=model, test_dataloaders=testloader)

    # return the model
    return model

def initialize_model(model='UNet', num_classes=3, lr=3e-4, k=2):
    """
    Function for initializing a model based on the given command line arguments.
    
    Inputs:
        model - String indicating the model to use. Default = 'LeNet'
        num_classes - Int indicating the number of classes. Default = 10
        lr - Float indicating the optimizer learning rate. Default = 3e-4
        k - Level of anonimity. k-1 fake features are generated
            to train the discriminator. Default = 2
    """
    
    # initialize the model if possible
    if model in model_dict:
        return model_dict[model](num_classes=num_classes, training=True)
    # alert the user if the given model does not exist
    else:
        assert False, "Unknown model name \"%s\". Available models are: %s" % (model_name, str(model_dict.keys()))
        
def load_data_fn(dataset='CIFAR-10', batch_size=256, num_workers=0):
    """
    Function for loading a dataset based on the given command line arguments.
    
    Inputs:
        dataset - String indicating the dataset to use. Default = 'CIFAR-10'
        batch_size - Int indicating the size of the mini batches. Default = 256
        num_workers - Int indicating the number of workers to use in the dataloader. Default = 0 (truly deterministic)
    """
    
    # load the dataset if possible
    if dataset in dataset_dict:
        return dataset_dict[dataset](batch_size, num_workers)
    # alert the user if the given dataset does not exist
    else:
        assert False, "Unknown dataset name \"%s\". Available datasets are: %s" % (dataset, str(dataset_dict.keys()))

if __name__ == '__main__':
    """
    Direct calling of the python file via command line.
    Handles the given hyperparameters.
    """
    
    # initialize the parser for the command line arguments
    parser = argparse.ArgumentParser()
    
    # model hyperparameters
    parser.add_argument('--model', default='UNet', type=str,
                        help='What model to use. Default is Complex_LeNet.',
                        choices=['UNet'])
    parser.add_argument('--dataset', default='CIFAR-10', type=str,
                        help='What dataset to use. Default is CIFAR-10.',
                        choices=['CIFAR-10', 'CIFAR-100', 'CelebA'])
    
    # dataloader hyperparameters
    parser.add_argument('--batch_size', default=64, type=int,
                        help='Minibatch size. Default is 4.')
    parser.add_argument('--num_workers', default=0, type=int,
                        help='Number of workers to use in the data loaders. Default is not 0 (truly deterministic).')
                        
    # training hyperparameters
    parser.add_argument('--epochs', default=10, type=int,
                        help='Max number of epochs. Default is 10.')
    parser.add_argument('--k', default=2, type=int,
                        help='Level of anonimity to use during training. k-1 fake features are generated to train the encoder. Default is 2,')                   
    parser.add_argument('--log_dir', default='attacker_logs/', type=str,
                        help='Directory where the PyTorch Lightning logs are created. Default is GAN_logs/.')
    parser.add_argument('--load_dict', default=None, type=str,
                        help='Directory where the model is stored. Default is inference_attack_model.')
    parser.add_argument('--progress_bar', action='store_true',
                        help='Use a progress bar indicator. Disabled by default.')
    parser.add_argument('--seed', default=42, type=int,
                        help='Seed to use for reproducing results. Default is 42.')
                        
    # optimizer hyperparameters
    parser.add_argument('--lr', default=3e-4, type=float,
                        help='Learning rate to use. Default is 3e-4.')
    
    # parse the arguments 
    args = parser.parse_args()

    # train the model with the given arguments
    train_model(args)