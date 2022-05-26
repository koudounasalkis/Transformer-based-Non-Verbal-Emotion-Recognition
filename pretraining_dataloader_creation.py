import os
import pandas as pd
import argparse
from sklearn import preprocessing
import torch
from torch.utils.data import DataLoader

from datasets.pretraining_dataset import pretraining_dataset

parser = argparse.ArgumentParser(description="Create dataloader for pretraining step")
parser.add_argument(
        "--csv_folder",
        help="Input folder containing the csv files of each split",
        required=True)
parser.add_argument(
        "--wav_folder",
        help="Input folder containing the wav files",
        required=True)
parser.add_argument(
        "--output_folder",
        help="Output folder to store dataloaders",
        required=True)

args = parser.parse_args()

if not os.path.isdir(args.output_folder):
    os.mkdir(args.output_folder)

train_df = pd.read_csv(os.path.join(args.csv_folder, "train.csv"))
le = preprocessing.LabelEncoder()
le.fit(train_df.label)
train_df['categorical_label'] = le.transform(train_df.label)

train_dataloader = pretraining_dataset(train_df, args.wav_folder)
train_dataloader = DataLoader(train_dataloader, shuffle=True)
torch.save(train_dataloader, os.path.join(args.output_folder, "train_dataloader.bkp"))