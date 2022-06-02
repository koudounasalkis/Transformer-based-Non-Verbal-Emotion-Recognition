import os
import torch
from transformers import AutoModelForAudioClassification, TrainingArguments, Trainer, AutoFeatureExtractor, EarlyStoppingCallback
import numpy as np 
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support, accuracy_score
import librosa
import torch.nn as nn
from sklearn.utils import class_weight
import argparse
from tqdm import tqdm
from datasets.finetuning_dataset import finetuning_dataset
import warnings
warnings.filterwarnings("ignore")

path = '../../../data1/akoudounas/vocalisation/'

""" Trainer Class """
class WeightedTrainer(Trainer):
    def __init__(self, class_weights, **kwargs):
        super().__init__(**kwargs)
        self.class_weights = class_weights
    
    def compute_loss(self, model, inputs, return_outputs=False):
        labels = inputs.get("labels").long()
        outputs = model(**inputs)
        logits = outputs.get("logits")
        loss_fct = nn.CrossEntropyLoss(weight=self.class_weights)
        loss = loss_fct(logits.view(-1, self.model.config.num_labels), labels.view(-1))
        return (loss, outputs) if return_outputs else loss
    

""" Define Metric """
def compute_metrics(pred):
    labels = pred.label_ids
    preds = np.argmax(pred.predictions, axis=1)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, preds, average='weighted')
    acc = accuracy_score(labels, preds)

    print('F1 score: ' + str(f1))
    print('Accuracy: ' + str(acc))
    print('Precision: ' + str(precision))
    print('Recall: ' + str(recall))
      
    return {
        'accuracy': acc,
        'f1': f1,
        'precision': precision,
        'recall': recall
    }


""" Define Command Line Parser """
def parse_cmd_line_params():
    parser = argparse.ArgumentParser(description="WavLM finetuning")
    parser.add_argument(
        "--csv_folder",
        help="Input folder containing the csv files of each split",
        required=True)
    parser.add_argument(
        "--batch_size",
        help="Batch size",
        default=16, 
        type=int,
        required=False)
    parser.add_argument(
        "--n_workers",
        help="Number of workers",
        type=int,
        default=4,
        required=False)
    parser.add_argument(
        "--n_epochs",
        help="Number of finetuning epochs",
        type=int,
        default=20,
        required=False)
    parser.add_argument(
        "--learning_rate",
        help="Learning rate",
        type=float,
        default=3e-5,
        required=False)
    args = parser.parse_args()
    return args


""" Main Program """
if __name__ == '__main__':
    
    ## Utils 
    torch.multiprocessing.set_start_method('spawn')
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    max_duration = 5.0 
    args = parse_cmd_line_params()


    """ Preprocess Data """
    ## Train
    df_train = pd.read_csv(os.path.join(args.csv_folder, 'train.csv'))
    emotions = df_train['label'].unique()

    ## Prepare the labels
    label2id, id2label = dict(), dict()
    for i, label in enumerate(emotions):
        label2id[label] = str(i)
        id2label[str(i)] = label
    num_labels = len(id2label)

    for index in tqdm(df_train.index):
        df_train.loc[index,'filename'] = path + df_train.loc[index,'filename']
        df_train.loc[index,'label'] = label2id[df_train.loc[index,'label']]
    df_train['label'] = df_train['label'].astype(int)
    #df_train.to_csv('df_train.csv', index=False)

    df_valid = pd.read_csv(os.path.join(args.csv_folder, 'devel.csv'))
    for index in tqdm(df_valid.index):
        df_valid.loc[index,'filename'] = path + df_valid.loc[index,'filename']
        df_valid.loc[index,'label'] = label2id[df_valid.loc[index,'label']]
    df_valid['label'] = df_valid['label'].astype(int)
    #df_valid.to_csv('df_valid.csv', index=False)


    """ Define Model """
    # model_checkpoint = "facebook/wav2vec2-xls-r-300m"
    model_checkpoint = "microsoft/wavlm-large"   
    feature_extractor = AutoFeatureExtractor.from_pretrained(model_checkpoint)
    model = AutoModelForAudioClassification.from_pretrained(
        model_checkpoint, 
        num_labels=num_labels,
        label2id=label2id,
        id2label=id2label
    )

    """ Build Dataset """
    train_dataset = finetuning_dataset(df_train, feature_extractor, max_duration, device)
    valid_dataset = finetuning_dataset(df_valid, feature_extractor, max_duration, device)

    """ Training Model """
    model_name = model_checkpoint.split("/")[-1]
    batch_size = args.batch_size
    output_dir = path + model_name + "-finetuned-vocalisation"

    # Define args
    training_args = TrainingArguments(
        output_dir=output_dir,
        overwrite_output_dir=True,
        evaluation_strategy = "epoch",
        save_strategy = "epoch",
        learning_rate=args.learning_rate,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        per_device_eval_batch_size=batch_size,
        num_train_epochs=args.n_epochs,
        warmup_ratio=0.1,
        logging_steps=30,
        eval_steps=30,
        save_steps=30,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        fp16=True,
        fp16_full_eval=True,
        dataloader_num_workers=args.n_workers,
        dataloader_pin_memory=True,
    )

    ## Class Weights
    class_weights = class_weight.compute_class_weight(
        'balanced',
        classes=np.unique(df_train["label"]),
        y=np.array(df_train["label"])
    )
    class_weights = torch.tensor(class_weights, device="cuda", dtype=torch.float32)


    ## Trainer 
    early_stopping = EarlyStoppingCallback(early_stopping_patience=2)
    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=valid_dataset,
        callbacks=[early_stopping],
        compute_metrics=compute_metrics
    )

    # Train and Evaluate
    trainer.train()
    trainer.save_model(output_dir)
    trainer.evaluate()