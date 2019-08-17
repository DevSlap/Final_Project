
The configuration of the VM in the Google Cloud Platform is given below.
Machine type – n1 standard vCPU * 8, 30 GB memory and 1 NIVIDIA Tesla K80 GPU

The submissionfiles directory contains the following subdirectories.

•	Code – contains the source code written in python. This directory has two subdirectories. QA_word_embed, which contains the code for the model that includes word embedding. QA_char_word_embed, which contains the code for the model that includes both word and character embedding. 

•	results – The results directory contains the results generated from each model as an XML file. The output of all the 8 models can be found here. 

•	log_dir – This directory contains the output log while conducting the training.
