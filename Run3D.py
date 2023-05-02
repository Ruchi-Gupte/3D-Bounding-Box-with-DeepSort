## INBUILT YOLO FUNCTIONS
from yolov5.utils.general import non_max_suppression, scale_coords
from yolov5.utils.torch_utils import select_device
from yolov5.utils.datasets import letterbox
import torch.backends.cudnn as cudnn

from Utils.Math import *
from Utils.helper import *
from Utils import ClassAverages
from Train_3D_Features import Model
import sys

import os
import time

import numpy as np
import cv2

import torch
import torch.nn as nn
from torchvision.models import vgg
from torchvision import transforms


url = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(url, 'yolov5')))
cudnn.benchmark = True
transform = transforms.Compose([transforms.ToTensor(), transforms.Resize((224, 224)), transforms.Normalize((0.485, 0.456, 0.406),(0.229, 0.224, 0.225))])
    
def main():
    yolo_model_path = 'yolov5/weights/yolov5s.pt'
    model_path =  url + '/Train_3D_Features/trained_models/epoch_10.pkl'
    
    img_path = url + "/eval/2011_09_26/image_02/data/"
    calib_file = url + "/eval/2011_09_26/calib_cam_to_cam.txt"

    device = select_device('')

    detector = torch.load(yolo_model_path, map_location=device)['model'].float()  
    detector.to(device).eval()
    names = detector.module.names if hasattr(detector, 'module') else detector.names        
    
    my_vgg = vgg.vgg19_bn(pretrained=True)
    model = Model.Model(features=my_vgg.features, bins=2).to(device)

    if torch.cuda.is_available():
        checkpoint = torch.load(model_path)
    else:
        checkpoint = torch.load(model_path,map_location=torch.device('cpu'))

    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    averages = ClassAverages.ClassAverages()
    angle_bins = generate_bins(2)

    image_list = [x.split('.')[0] for x in sorted(os.listdir(img_path))]
    print("No of images:", len(image_list))
    proj_matrix = get_P(calib_file)
    # R0 = get_R0(calib_file)
    # Tr = get_tr_to_velo(calib_file)
    for img_id in image_list:
        img_file = img_path + img_id + ".png"
        truth_img = cv2.imread(img_file)
        img = np.copy(truth_img)
        yolo_img = np.copy(truth_img)

        v5img = letterbox(yolo_img)[0]
        v5img = v5img[:, :, ::-1].transpose(2, 0, 1)  # BGR to RGB
        v5img = np.ascontiguousarray(v5img)

        v5img = torch.from_numpy(v5img).to(device)
        v5img = v5img.float() 
        v5img = v5img/255.0  

        if v5img.ndimension() == 3:
            v5img = torch.unsqueeze(v5img,0)

        alldetections = detector(v5img, augment=True)[0]
        detections = non_max_suppression(alldetections, 0.5, 0.5, agnostic=True)[0]
        if detections is None:
            continue
        detections[:, :4] = scale_coords(v5img.shape[2:], detections[:, :4], truth_img.shape).round()
        
        for detection in detections:
            detection = detection.cpu().numpy()
            matrix = detection[:4].astype(int).reshape(-1, 2).T
            box2d = [tuple(row) for row in matrix.T]
            detected_class = names[int(detection[-1])]

            if not averages.recognized_class(detected_class):
                continue

            theta_ray = calc_theta_ray(img, box2d, proj_matrix)
            xl, yl = box2d[0]
            xr, yr = box2d[1]
            input_tensor = transform(img[yl:yr+1, xl:xr+1]).reshape(1,3,224,224).to(device)

            [orient, conf, dim] = model(input_tensor)
            orient = orient.cpu().data.numpy()[0, :, :]
            conf = conf.cpu().data.numpy()[0, :]
            dim = dim.cpu().data.numpy()[0, :]

            dim += averages.get_item(detected_class)

            argmax = np.argmax(conf)
            orient = orient[argmax, :]
            cos = orient[0]
            sin = orient[1]
            alpha = np.arctan2(sin, cos)
            alpha += angle_bins[argmax]
            alpha -= np.pi

            #Plot 2D and 3D box
            location, _ = calc_location(dim, proj_matrix, box2d, alpha, theta_ray)

            orient = alpha + theta_ray
            plot_2d_box(truth_img, box2d, '1')
            img = plot_3d_box(img, proj_matrix, orient, dim, location, '1', box2d) # 3d boxes

        numpy_vertical = np.concatenate((truth_img, img), axis=0)
        new_height = int(1024 * 4/5)
        new_width = int(1392 * 4/5)
        # Resize the image
        numpy_vertical = cv2.resize(numpy_vertical, (new_width, new_height))
        cv2.imshow('2D vs 3D detections', numpy_vertical)
        cv2.waitKey(5)
       
if __name__ == '__main__':
    main()
