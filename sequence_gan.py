
import numpy as np
import tensorflow as tf
import random

from dataloader import Gen_Data_loader, Dis_dataloader
from generator import Generator
from discriminator import Discriminator
from rollout import ROLLOUT
import cPickle

import logger


USE_GPU = False


#########################################################################################
#  Data & Basic Training Params
#########################################################################################

# previously: 5000
VOCAB_SIZE = 652  # There are this many unique labels in the trajectory file
# previously: 20
SEQ_LENGTH = 122  # <-- for trajectory data # sequence length

real_file = 'data/relabeled_trajectories_1_workweek.txt'
fake_file = 'save/generated_trajectories.txt'
eval_file = 'save/eval_file_{}.txt'

TOTAL_BATCH = 250
generated_num = 5000  #  Previously set to 10,000; num trajectories: 23238.
eval_generated_num = 500 # For eval files, print less


#########################################################################################
#  Generator  Hyper-parameters
######################################################################################
EMB_DIM = 128 # embedding dimension -- Changed from original value of 32
HIDDEN_DIM = 64 # hidden state dimension of lstm cell
START_TOKEN = 1  # Changed from original value of 0.
PRE_EPOCH_NUM = 120  # supervise (maximum likelihood estimation) epochs
SEED = 88
BATCH_SIZE = 50

#########################################################################################
#  Discriminator  Hyper-parameters
#########################################################################################
dis_embedding_dim = EMB_DIM
dis_filter_sizes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20]
dis_num_filters = [100, 200, 200, 200, 200, 100, 100, 100, 100, 100, 160, 160]
dis_dropout_keep_prob = 0.75
dis_l2_reg_lambda = 0.2
dis_batch_size = 50


def generate_samples(sess, trainable_model, batch_size, generated_num, output_file):
    # Generate Samples
    generated_samples = []
    for _ in range(int(generated_num / batch_size)):
        generated_samples.extend(trainable_model.generate(sess))

    with open(output_file, 'w') as fout:
        for sample in generated_samples:
            buffer = ' '.join([str(x) for x in sample]) + '\n'
            fout.write(buffer)


def pre_train_epoch(sess, trainable_model, data_loader):
    # Pre-train the generator using MLE for one epoch
    supervised_g_losses = []
    data_loader.reset_pointer()

    for it in xrange(data_loader.num_batch):
        batch = data_loader.next_batch()
        _, g_loss = trainable_model.pretrain_step(sess, batch)
        supervised_g_losses.append(g_loss)

    return np.mean(supervised_g_losses)


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    # TODO: I changed this.  Why was this asserted?  Was it just to ensure the replication
    # of results?  Or is zero important otherwise?
    # Changed because 0 is a bad start token for our data.  (cannot have home label=0)
    # assert START_TOKEN == 0

    # set up logging
    log_fpath = logger.get_experiment_log_filepath()

    gen_data_loader = Gen_Data_loader(BATCH_SIZE, SEQ_LENGTH)
    likelihood_data_loader = Gen_Data_loader(BATCH_SIZE, SEQ_LENGTH) # For testing
    vocab_size = VOCAB_SIZE
    dis_data_loader = Dis_dataloader(BATCH_SIZE, SEQ_LENGTH)

    generator = Generator(vocab_size, BATCH_SIZE, EMB_DIM, HIDDEN_DIM, SEQ_LENGTH, START_TOKEN)
    discriminator = Discriminator(sequence_length=SEQ_LENGTH, num_classes=2, vocab_size=vocab_size,
                                    embedding_size=dis_embedding_dim, filter_sizes=dis_filter_sizes,
                                    num_filters=dis_num_filters, l2_reg_lambda=dis_l2_reg_lambda)

    if not USE_GPU:
        # Prevent the environment from seeing the available GPUs (to avoid error on matlaber cluster)
        import os
        os.environ["CUDA_VISIBLE_DEVICES"]="-1"
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    sess = tf.Session(config=config)
    sess.run(tf.global_variables_initializer())

    gen_data_loader.create_batches(real_file)

    #  pre-train generator
    logger.write_log(log_fpath, 'pre-training generator...')
    for epoch in xrange(PRE_EPOCH_NUM):
        loss = pre_train_epoch(sess, generator, gen_data_loader)
        if epoch % 5 == 0:
            logger.write_log(log_fpath, 'generator loss:')
            logger.log_progress(log_fpath, epoch, loss)
            generate_samples(sess, generator, BATCH_SIZE, eval_generated_num, eval_file.format('pretrain'))

    logger.write_log(log_fpath, 'Start pre-training discriminator...')
    # Train 3 epoch on the generated data and do this for 50 times
    for i in range(50):
        generate_samples(sess, generator, BATCH_SIZE, generated_num, fake_file)
        dis_data_loader.load_train_data(real_file, fake_file)
        # dis_data_loader.load_train_data(positive_file, negative_file)
        logger.write_log(log_fpath, 'epoch iterator:  %s / 50' % i)
        for j in range(3):
            dis_data_loader.reset_pointer()
            for it in xrange(dis_data_loader.num_batch):
                x_batch, y_batch = dis_data_loader.next_batch()
                feed = {
                    discriminator.input_x: x_batch,
                    discriminator.input_y: y_batch,
                    discriminator.dropout_keep_prob: dis_dropout_keep_prob
                }
                _d_train_output = sess.run(discriminator.train_op, feed)

    logger.write_log(log_fpath, 'finished pre-training discriminator')
    rollout = ROLLOUT(generator, 0.8)

    logger.write_log(log_fpath, 'Start Adversarial Training...')
    g_steps = 1
    d_steps = 1
    k = 10
    for batch in range(TOTAL_BATCH):
        buff = 'batch %s/%s' % (batch, TOTAL_BATCH)
        logger.write_log(log_fpath, buff)
        # Train the generator for one step
        for it in range(g_steps):
            samples = generator.generate(sess)
            rollout_num = 16  # TODO: experiment with this value
            rewards = rollout.get_reward(sess, samples, rollout_num, discriminator)
            feed = {generator.x: samples, generator.rewards: rewards}
            _ = sess.run(generator.g_updates, feed_dict=feed)

        # Test
        if batch % 5 == 0 or batch == TOTAL_BATCH - 1:
            generate_samples(sess, generator, BATCH_SIZE, eval_generated_num, eval_file.format(batch))
            logger.write_log(log_fpath, 'generated some more eval samples...')

        # Update roll-out parameters
        rollout.update_params()

        # Train the discriminator
        for _ in range(d_steps):
            generate_samples(sess, generator, BATCH_SIZE, generated_num, fake_file)
            dis_data_loader.load_train_data(real_file, fake_file)

            for _ in range(k):
                dis_data_loader.reset_pointer()
                for it in xrange(dis_data_loader.num_batch):
                    x_batch, y_batch = dis_data_loader.next_batch()
                    feed = {
                        discriminator.input_x: x_batch,
                        discriminator.input_y: y_batch,
                        discriminator.dropout_keep_prob: dis_dropout_keep_prob
                    }
                    _ = sess.run(discriminator.train_op, feed)

    logger.write_log(log_fpath, 'I\'M DONE')


if __name__ == '__main__':
    main()
