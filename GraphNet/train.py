from __future__ import print_function

# TEMP
import psutil


import resource
# Don't have permissions for this on pod...
#resource.setrlimit(resource.RLIMIT_NOFILE, (1048576, 1048576))

import numpy as np
import torch
from torch.utils.data import DataLoader

import tqdm
import os
import datetime
import argparse

from utils.ParticleNet import ParticleNet
from dataset import ECalHitsDataset
from dataset import collate_wrapper as collate_fn
from utils.SplitNet import SplitNet

parser = argparse.ArgumentParser()
parser.add_argument('--demo', action='store_true', default=False,
                    help='quickly test the setup by running over only a small number of events')
parser.add_argument('--coord-ref', type=str, default='none', choices=['none', 'ecal_sp', 'target_sp', 'ecal_centroid'],
                    help='refernce points for the x-y coordinates')
parser.add_argument('--network', type=str, default='particle-net-lite', choices=['particle-net', 'particle-net-lite', 'particle-net-k5', 'particle-net-k7'],
                    help='network architecture')
parser.add_argument('--focal-loss-gamma', type=float, default=2,
                    help='value of the gamma parameter if focal loss is used; when setting to 0, will use simple cross-entropy loss')
parser.add_argument('--save-model-path', type=str, default='models/particle_net_model',
                    help='path to save the model during training')
parser.add_argument('--num-epochs', type=int, default=20,
                    help='number of epochs')
parser.add_argument('--optimizer', type=str, default='ranger', choices=['adam', 'ranger'],
                    help='optimizer for the training')
parser.add_argument('--start-lr', type=float, default=5e-3,
                    help='start learning rate')
parser.add_argument('--lr-steps', type=str, default='10,20',
                    help='steps to reduce the lr')
parser.add_argument('--batch-size', type=int, default=128,
                    help='batch size')
parser.add_argument('--device', type=str, default='cuda:0',
                    help='device for the training')
parser.add_argument('--num-workers', type=int, default=2,
                    help='number of threads to load the dataset')

parser.add_argument('--predict', action='store_true', default=False,
                    help='run prediction instead of training')
parser.add_argument('--load-model-path', type=str, default='',
                    help='path to the model for prediction')
parser.add_argument('--test-sig', type=str, default='',
                    help='signal sample to be used for testing')
parser.add_argument('--test-bkg', type=str, default='',
                    help='background sample to be used for testing')
parser.add_argument('--save-extra', action='store_true', default=False,
                    help='save extra information defined in `obs_branches` to the prediction output')
parser.add_argument('--test-output-path', type=str, default='test-outputs/particle_net_output',
                    help='path to save the prediction output')

args = parser.parse_args()

###### location of the signal and background files ######
bkglist = {
    # (filepath, num_events_for_training)
    #0: ('/data/hqu/ldmx/mc/v9/4gev_1e_ecal_pn_02_1.48e13_gab/*.root', -1)
    0: ('/home/pmasterson/GraphNet_input/v12/*pn*.root', -1)
    }

siglist = {
    # (filepath, num_events_for_training)
    #1: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.0.001*.root', 200000),
    #10: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.0.01*.root', 200000),
    #100: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.0.1*.root', 200000),
    #1000: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.1.0*.root', 200000),
    1:    ('/home/pmasterson/GraphNet_input/v12/*0.001*.root', 200000),
    10:   ('/home/pmasterson/GraphNet_input/v12/*0.01*.root',  200000),
    100:  ('/home/pmasterson/GraphNet_input/v12/*0.1*.root',   200000),
    1000: ('/home/pmasterson/GraphNet_input/v12/*1.0*.root',   200000),
    }

if args.demo:
    bkglist = {
        # (filepath, num_events_for_training)
        #0: ('/data/hqu/ldmx/mc/v9/4gev_1e_ecal_pn_02_1.48e13_gab/*.root', 4000)
        0: ('/home/pmasterson/GraphNet_input/v12/*pn*.root', 4000)
        }

    siglist = {
        # (filepath, num_events_for_training)
        #1: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.0.001*.root', 1000),
        #10: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.0.01*.root', 1000),
        #100: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.0.1*.root', 1000),
        #1000: ('/data/hqu/ldmx/mc/v9/signal_hs/*mA.1.0*.root', 1000),
        1:    ('/home/pmasterson/GraphNet_input/v12/*0.001*.root', 1000),
        10:   ('/home/pmasterson/GraphNet_input/v12/*0.01*.root',  1000),
        100:  ('/home/pmasterson/GraphNet_input/v12/*0.1*.root',   1000),
        1000: ('/home/pmasterson/GraphNet_input/v12/*1.0*.root',   1000),
        }
#########################################################

###### `observer` variables to be saved in the prediction output ######
obs_branches = []
if args.save_extra:
    # NOW using v12:
    obs_branches = [
        #'ecalDigis_recon.id_',
        #'ecalDigis_recon.energy_',

        'EcalVeto_v12.nReadoutHits_',
        'EcalVeto_v12.deepestLayerHit_',
        'EcalVeto_v12.summedDet_',
        'EcalVeto_v12.summedTightIso_',
        'EcalVeto_v12.maxCellDep_',
        'EcalVeto_v12.showerRMS_',
        'EcalVeto_v12.xStd_',
        'EcalVeto_v12.yStd_',
        'EcalVeto_v12.avgLayerHit_',
        'EcalVeto_v12.stdLayerHit_',
        'EcalVeto_v12.ecalBackEnergy_',
        'EcalVeto_v12.electronContainmentEnergy_',
        'EcalVeto_v12.photonContainmentEnergy_',
        'EcalVeto_v12.outsideContainmentEnergy_',
        'EcalVeto_v12.outsideContainmentNHits_',
        'EcalVeto_v12.outsideContainmentXStd_',
        'EcalVeto_v12.outsideContainmentYStd_',
        'EcalVeto_v12.discValue_',
        'EcalVeto_v12.recoilPx_',
        'EcalVeto_v12.recoilPy_',
        'EcalVeto_v12.recoilPz_',
        'EcalVeto_v12.recoilX_',
        'EcalVeto_v12.recoilY_',
        'EcalVeto_v12.ecalLayerEdepReadout_',

        'TargetSPRecoilE_pt',
        ]
#########################################################
#########################################################

# training/testing mode
if args.predict:
    assert(args.load_model_path)
    training_mode = False
    if args.test_sig or args.test_bkg:
        bkglist = {}
        siglist = {}
        if args.test_sig:
            siglist = {
                # label: (filepath, num_events_for_training)
                -1: (args.test_sig, -1)
                }

        if args.test_bkg:
            bkglist = {
                # label: (filepath, num_events_for_training)
                0: (args.test_bkg, -1),
                }
else:
    training_mode = True

# model parameter
if args.network == 'particle-net':
    conv_params = [
        (16, (64, 64, 64)),
        (16, (128, 128, 128)),
        (16, (256, 256, 256)),
        ]
    fc_params = [(256, 0.1)]
elif args.network == 'particle-net-lite':
    conv_params = [
        (7, (32, 32, 32)),
        (7, (64, 64, 64))
        ]
    fc_params = [(128, 0.1)]
elif args.network == 'particle-net-k5':
    conv_params = [
        (5, (64, 64, 64)),
        (5, (128, 128, 128)),
        (5, (256, 256, 256)),
        ]
    fc_params = [(256, 0.1)]
elif args.network == 'particle-net-k7':
    conv_params = [
        (7, (64, 64, 64)),
        (7, (128, 128, 128)),
        (7, (256, 256, 256)),
        ]
    fc_params = [(256, 0.1)]

print('conv_params: %s' % conv_params)
print('fc_params: %s' % fc_params)

# device
dev = torch.device(args.device)

# load data
if training_mode:
    # for training: we use the first 0-20% for testing, and 20-80% for training
    print("Usage: {}".format(psutil.virtual_memory().percent))
    train_data = ECalHitsDataset(siglist=siglist, bkglist=bkglist, load_range=(0.2, 1), coord_ref=args.coord_ref)
    print("Usage: {}".format(psutil.virtual_memory().percent))
    val_data = ECalHitsDataset(siglist=siglist, bkglist=bkglist, load_range=(0, 0.2), coord_ref=args.coord_ref)
    print("Usage: {}".format(psutil.virtual_memory().percent))
    train_loader = DataLoader(train_data, num_workers=args.num_workers, batch_size=args.batch_size,
                              collate_fn=collate_fn, shuffle=True, drop_last=True, pin_memory=True)
    print("Usage: {}".format(psutil.virtual_memory().percent))
    val_loader = DataLoader(val_data, num_workers=args.num_workers, batch_size=args.batch_size,
                            collate_fn=collate_fn, shuffle=False, drop_last=False, pin_memory=True)
    print("Usage: {}".format(psutil.virtual_memory().percent))
    print('Train: %d events, Val: %d events' % (len(train_data), len(val_data)))
    print('Using val sample for testing!')
    test_data = val_data
    test_loader = val_loader
else:
    test_frac = (0, 1) if args.test_sig or args.test_bkg else (0, 0.2)
    test_data = ECalHitsDataset(siglist=siglist, bkglist=bkglist, load_range=test_frac, ignore_evt_limits=(not args.demo), obs_branches=obs_branches, coord_ref=args.coord_ref)
    test_loader = DataLoader(test_data, num_workers=args.num_workers, batch_size=args.batch_size,
                            collate_fn=collate_fn, shuffle=False, drop_last=False, pin_memory=True)

input_dims = test_data.num_features

# model
print("Initializing model")
print("Usage: {}".format(psutil.virtual_memory().percent))
model = SplitNet(input_dims=input_dims, num_classes=2,
                 conv_params=conv_params,
                 fc_params=fc_params,
                 use_fusion=True)

model = model.to(dev)


def train(model, opt, scheduler, train_loader, dev):
    model.train()

    total_loss = 0
    num_batches = 0
    total_correct = 0
    count = 0
    with tqdm.tqdm(train_loader) as tq:
        for batch in tq:
            label = batch.label
            num_examples = label.shape[0]
            label = label.to(dev).squeeze().long()
            opt.zero_grad()
            logits = model(batch.coordinates.to(dev), batch.features.to(dev))
            #print("label.shape=", label.shape)
            #print("logits.shape=", logits.shape)
            #print("label =", label)
            loss = loss_func(logits, label)
            loss.backward()
            opt.step()

            _, preds = logits.max(1)

            num_batches += 1
            count += num_examples
            loss = loss.item()
            correct = (preds == label).sum().item()
            total_loss += loss
            total_correct += correct

            tq.set_postfix({
                'Loss': '%.5f' % loss,
                'AvgLoss': '%.5f' % (total_loss / num_batches),
                'Acc': '%.5f' % (correct / num_examples),
                'AvgAcc': '%.5f' % (total_correct / count)})

    scheduler.step()


def evaluate(model, test_loader, dev, return_scores=False):
    model.eval()

    total_correct = 0
    count = 0
    scores = []

    with torch.no_grad():
        with tqdm.tqdm(test_loader) as tq:
            for batch in tq:
                label = batch.label
                num_examples = label.shape[0]
                label = label.to(dev).squeeze().long()
                logits = model(batch.coordinates.to(dev), batch.features.to(dev))
                _, preds = logits.max(1)

                if return_scores:
                    scores.append(torch.softmax(logits, dim=1).cpu().detach().numpy())

                correct = (preds == label).sum().item()
                total_correct += correct
                count += num_examples

                tq.set_postfix({
                    'Acc': '%.5f' % (correct / num_examples),
                    'AvgAcc': '%.5f' % (total_correct / count)})

    if return_scores:
        return np.concatenate(scores)
    else:
        return total_correct / count


if training_mode:
    # loss function
    if args.focal_loss_gamma > 0:
        print('Using focal loss w/ gamma=%s' % args.focal_loss_gamma)
        from utils.focal_loss import FocalLoss
        loss_func = FocalLoss(gamma=args.focal_loss_gamma)
    else:
        loss_func = torch.nn.CrossEntropyLoss()

    # optimizer & learning rate
    if args.optimizer == 'adam':
        opt = torch.optim.Adam(model.parameters(), lr=args.start_lr)
        lr_steps = [int(x) for x in args.lr_steps.split(',')]
        scheduler = torch.optim.lr_scheduler.MultiStepLR(opt, milestones=lr_steps, gamma=0.1)
    else:
        from utils.ranger import Ranger
        opt = Ranger(model.parameters(), lr=args.start_lr)
        lr_decay_epochs = int(args.num_epochs * 0.3)
        lr_decay_rate = 0.01 ** (1. / lr_decay_epochs)
        scheduler = torch.optim.lr_scheduler.MultiStepLR(opt, milestones=list(range(args.num_epochs - lr_decay_epochs, args.num_epochs)), gamma=lr_decay_rate)

    # training loop
    best_valid_acc = 0
    for epoch in range(args.num_epochs):
        train(model, opt, scheduler, train_loader, dev)

        print('Epoch #%d Validating' % epoch)
        valid_acc = evaluate(model, val_loader, dev)
        if valid_acc > best_valid_acc:
            best_valid_acc = valid_acc
            if args.save_model_path:
                dirname = os.path.dirname(args.save_model_path)
                if dirname and not os.path.exists(dirname):
                    os.makedirs(dirname)
                torch.save(model.state_dict(), args.save_model_path + '_state.pt')
                torch.save(model, args.save_model_path + '_full.pt')
        torch.save(model.state_dict(), args.save_model_path + '_state_epoch-%d_acc-%.4f.pt' % (epoch, valid_acc))
        print('Current validation acc: %.5f (best: %.5f)' % (valid_acc, best_valid_acc))

# load saved model
model_path = args.load_model_path if args.predict else args.save_model_path
if not model_path.endswith('.pt'):
    model_path += '_state.pt'
print('Loading model %s for eval' % model_path)
model.load_state_dict(torch.load(model_path))

# evaluate model on test dataset
path, name = os.path.split(args.test_output_path)
if path and not os.path.exists(path):
    os.makedirs(path)

test_preds = evaluate(model, test_loader, dev, return_scores=True)
test_labels = test_data.label
test_extra_labels = test_data.extra_labels

info_dict = {'model_name':args.network,
             'model_params': {'conv_params':conv_params, 'fc_params':fc_params},
             'coord_ref':args.coord_ref,
             'date': str(datetime.date.today()),
             'model_path': args.load_model_path,
             'siglist': siglist,
             'bkglist': bkglist,
             'presel_eff': test_data.presel_eff,
             }
if training_mode:
    info_dict.update({'model_path': args.save_model_path})

from utils.plot_utils import plotROC, get_signal_effs
for k in siglist:
    if k > 0:
        mass = '%d MeV' % k
        fpr, tpr, auc, acc = plotROC(test_preds, test_labels, sample_weight=np.logical_or(test_extra_labels == 0, test_extra_labels == k),
                                     sig_eff=test_data.presel_eff[k], bkg_eff=test_data.presel_eff[0],
                                     output=os.path.splitext(args.test_output_path)[0] + 'ROC_%s.pdf' % mass, label=mass, xlim=[1e-6, .01], ylim=[0, 1], logx=True)
        info_dict[mass] = {'auc-presel': auc,
                           'acc-presel': acc,
                           'effs': get_signal_effs(fpr, tpr)
                           }

print(' === Summary ===')
for k in info_dict:
    print('%s: %s' % (k, info_dict[k]))

info_file = os.path.splitext(args.test_output_path)[0] + '_INFO.txt'
with open(info_file, 'w') as f:
    for k in info_dict:
        f.write('%s: %s\n' % (k, info_dict[k]))

# save prediction output
import awkward
pred_file = os.path.splitext(args.test_output_path)[0] + '_OUTPUT'
out_data = test_data.obs_data
out_data['ParticleNet_extra_label'] = test_extra_labels
out_data['ParticleNet_disc'] = test_preds[:, 1]
awkward.save(pred_file, out_data, mode='w')

# export to onnx
# NOTE:  This isn't currently being used for anything, but eats up RAM

"""
onnx_output = os.path.join(os.path.dirname(args.test_output_path), os.path.basename(model_path).replace('.pt', '.onnx'))
print('Exporting ONNX model to %s' % onnx_output)
import torch.onnx
model_softmax = SplitNet(input_dims=input_dims, num_classes=2,
                         conv_params=conv_params,
                         fc_params=fc_params,
                         use_fusion=True,
                         return_softmax=True)  # add softmax to convert output to [0, 1]

model_softmax.load_state_dict(torch.load(model_path))
model_softmax.to(dev)
for batch in test_loader:
    model_softmax.eval()
    inputs = (batch.coordinates.to(dev), batch.features.to(dev))
    torch.onnx.export(model_softmax, inputs, onnx_output,
                      input_names=['coordinates', 'features'],
                      output_names=['output'],
                      dynamic_axes={'coordinates':[0], 'features':[0]},
                      opset_version=11)
    break
"""
