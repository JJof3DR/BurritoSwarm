#!/usr/bin/env python  
import roslib
import rospy
import tf
from math import *
from nav_msgs.msg import Odometry
from sensor_msgs.msg import NavSatFix
import geometry_msgs.msg
import mavros
import mavros_msgs.srv
from mavros import setpoint as SP
from mavros import command
from threading import Thread
from tf.transformations import quaternion_from_euler
from tf.transformations import euler_from_quaternion
import time
import threading
import thread
import pid_controller
print "broadcasting"

import utm

#roslib.load_manifest('odom_publisher')

#import mavros
#mavros.set_namespace()
#pub = SP.get_pub_position_local(queue_size=10)
class brekinIt:
    def __init__(self, copter_id="1", mavros_string="/mavros/copter1"):
        rospy.init_node('velocity_goto_'+copter_id)
        mavros.set_namespace(mavros_string)  # initialize mavros module with default namespace
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.current_lat = 0.0
        self.current_lon = 0.0
        self.current_alt = 0.0
        self.throttle_update = 0.0
        self.attitude_publish = True
        self.mavros_string = mavros_string
        self.copter_id = copter_id

        self.pid_throttle = pid_controller.PID(P = 0.8, I = 0.8, D = 0.8, Integrator_max=1, Integrator_min=0)
        self.pid_throttle.setPoint(10)

        self.setHome = False
        self.home_lat = 0.0
        self.home_lon = 0.0
        self.home_alt = 0.0
        self.publish = True
        self.velocity_init()

    def setmode(self,base_mode=0,custom_mode="OFFBOARD",delay=0.1):
        # Optimize time delay
        set_mode = rospy.ServiceProxy(self.mavros_string+'/set_mode', mavros_msgs.srv.SetMode)  
        ret = set_mode(base_mode=base_mode, custom_mode=custom_mode)
        print "Changing modes: ", ret
        time.sleep(delay)
    
    def handle_pose(self, msg):
        pos = msg.pose.pose.position
        
        self.current_lat = pos.x 
        self.current_lon = pos.y
        self.current_alt = pos.z

        if not self.setHome:
            self.home_lat = self.current_lat
            self.home_lon = self.current_lon
            self.home_alt = self.current_alt
            self.setHome = True
        
    def handle_global_pose(self, msg):
        self.current_lat = msg.latitude
        self.current_lon = msg.longitude


        if not self.setHome:
            self.home_lat = self.current_lat
            self.home_lon = self.current_lon
            self.home_alt = self.current_alt
            self.setHome = True
        
    def reset_home(self):
        self.setHome = False
        
    def subscribe_pose(self):
        #rate = rospy.Rate(10.0)
        #while not rospy.is_shutdown():
        rospy.Subscriber(self.mavros_string+'/global_position/local',
                         Odometry,
                         self.handle_pose)
        ## rospy.Subscriber('/mavros/global_position/global',
        ##                  NavSatFix,
        ##                  self.handle_global_pose)
         
        rospy.spin()

    def subscribe_pose_thread(self):
        s = Thread(target=self.subscribe_pose, args=())
        s.daemon = True
        s.start()
        
    def arm(self):
        #print dir(mavros)
        arm = rospy.ServiceProxy(self.mavros_string+'/cmd/arming', mavros_msgs.srv.CommandBool)  
        print "Arm: ", arm(True)
        
    def disarm(self):
        arm = rospy.ServiceProxy(self.mavros_string+'/cmd/arming', mavros_msgs.srv.CommandBool)  
        print "Disarm: ", arm(False)
    
    """
    This /class/ sends position targets to FCU's position controller
    """
    def velocity_init(self):
        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0
        self.yaw = 0.0
        self.yaw_target = 0.0
        self.velocity_publish = False
        self.use_pid = True

        self.pid_alt = pid_controller.PID()
        self.pid_alt.setPoint(10.0)
        # publisher for mavros/setpoint_position/local
        self.pub_vel = SP.get_pub_velocity_cmd_vel(queue_size=10)
        # subscriber for mavros/local_position/local
        self.sub = rospy.Subscriber(mavros.get_topic('local_position', 'local'), SP.PoseStamped, self.temp)
 
        try:
            thread.start_new_thread(self.navigate, ())
        except:
            fault("Error: Unable to start thread")
 
        # TODO(simon): Clean this up.
        self.done = False
        self.done_evt = threading.Event()
 
    def navigate(self):
        rate = rospy.Rate(10)   # 10hz
        magnitude = 1  # in meters/sec

        msg = SP.TwistStamped(
            header=SP.Header(
                frame_id="base_footprint",  # no matter, plugin don't use TF
                stamp=rospy.Time.now()),    # stamp should update
        )
        i =0

        #angle_cont
        while not rospy.is_shutdown():
            #print "publishing velocity"
            self.throttle_update = self.pid_throttle.update(self.current_alt)
            pid_offset = self.pid_alt.update(self.current_alt)
            if self.use_pid:
                msg.twist.linear = geometry_msgs.msg.Vector3(self.vx*magnitude, self.vy*magnitude, self.vz*magnitude+pid_offset)
            else:
                msg.twist.linear = geometry_msgs.msg.Vector3(self.vx*magnitude, self.vy*magnitude, self.vz*magnitude)
                #msg.twist.linear = geometry_msgs.msg.Vector3(0, 1, self.vz*magnitude)

            # Yaw won't work
            yaw_degrees = self.yaw  # North
            yaw = radians(yaw_degrees)
            quaternion = quaternion_from_euler(0, 0, yaw)

            #msg.twist.angular = geometry_msgs.msg.Vector3(0,0,self.yaw_target)
            if self.velocity_publish:
                self.pub_vel.publish(msg)
            
            rate.sleep()
            i +=1

    def set_velocity_publish(self,pub):
        self.velocity_publish = pub
            
    def set_velocity(self, vx, vy, vz, yaw=0.0, delay=0, wait=False):
        self.done = False
        self.vx = vx
        self.vy = vy
        self.vz = vz
        
        self.yaw = yaw

        #print "Current Lat", self.current_lat, "Current Lon", self.current_lon
        
        if wait:
            rate = rospy.Rate(5)
            while not self.done and not rospy.is_shutdown():
                rate.sleep()
 
    def temp(self, topic):
        pass

    def velocity_gps_goto(self, lat, lon, alt):
        pid_lat = pid_controller.PID()
        pid_lon = pid_controller.PID()
        magnitude = 1.5 #m/s
        #pid_yaw = pid_controller.PID()

        #pid_yaw.setPoint(0)
        
        pid_lat.setPoint(lat)
        pid_lon.setPoint(lon)
        self.pid_alt.setPoint(alt)
        
        while True:
            #print "cur lat: ", self.current_lat, " target lat: ", lat, " cur lon: ", self.current_lon, " target lon: ", lon
            #print "self.vx: ", self.vx, "self.vy: ", self.vy
            self.vx = pid_lat.update(self.current_lat)
            self.vy = pid_lon.update(self.current_lon)
            if self.vx > magnitude:
                self.vx = magnitude
            if self.vx < -magnitude:
                self.vx = -magnitude
            if self.vy > magnitude:
                self.vy = magnitude
            if self.vy < -magnitude:
                self.vy = -magnitude

            print "a: ",abs(self.current_lat - lat), "b: ",abs(self.current_lon - lon)
            if abs(self.current_lon - lon) < 0.30 and abs(self.current_lat - lat) < 0.50:
                break

            
            #print "vely: ", self.vy, "velx: ", self.vx

            #self.yaw_target = pid_yaw.update(angle_error)

            
            ## if angle_error > 0:
            ##     self.yaw_target = -0.25
            ## elif angle_error < 0:
            ##     self.yaw_target = 0.25
            ## else:
            ##     self.yaw_target = 0

            ##if self.yaw_target > 0.25:
            ##    self.yaw_target = 0.25
            ##elif self.yaw_target < -0.25:
            ##    self.yaw_target = -0.25

            ## ##print "ANG ERROR: ", angle_error, " YAW Target: ", self.yaw_target
                
        self.pid_alt.setPoint(alt)
        self.use_pid = True
        pid_lat.setPoint(lat)

        self.set_velocity_publish(True)
        
        while abs(self.current_lat - lat) > 0.2:
            
            vel_x = pid_lat.update(self.current_lat)
            if vel_x > 5:
                vel_x = 5
            if vel_x < -5:
                vel_x = -5
            #self.publish_orientation()
            self.yaw = 67
            self.set_velocity(vel_x, 0, 0, yaw=60)
            print "ABS current lat min lat: ", abs(self.current_lat - lat)
            #print "Current lat, target lat: ", self.current_lat, " ", lat

    def land_velocity(self):
        self.use_pid = False
        #self.set_velocity(0, 0, -0.4)
        self.set_velocity(0, 0, -1)
        while self.current_alt > 0.2:
            print "landing: ", self.current_alt
        print "Landed, disarming"
        self.set_velocity(0, 0, 0)
        #self.disarm()

    def takeoff_velocity(self, alt=7):
        # Make margin hella better        
        self.use_pid = False
        while abs(self.current_alt - alt) > 0.2:
        
            self.x = 0
            self.y = 0
            self.z = 10
            self.set_velocity(0, 0, 2.5)
        

        time.sleep(0.1)
        
        rospy.loginfo("Reached target Alt!")
        self.use_pid = True

    def blocked_yaw(self, yaw = 167):
        att_pub = SP.get_pub_attitude_pose(queue_size=10)
        thd_pub = SP.get_pub_attitude_throttle(queue_size=10)

        #while not rospy.is_shutdown():
        pose = SP.PoseStamped(header=SP.Header(stamp=rospy.get_rostime()))
        q = quaternion_from_euler(0, 0, self.yaw)
        pose.pose.orientation = SP.Quaternion(*q)
        
        
        if self.attitude_publish or True:
            att_pub.publish(pose)
            thd_pub.publish(data=0.4)
            
            print "pose orientation: ", self.throttle_update
            #self.attitude_publish = False

class posVel:
    def __init__(self, copter_id = "1", mavros_string="/mavros/copter1"):
        rospy.init_node('velocity_goto_'+copter_id)
        mavros.set_namespace(mavros_string)  # initialize mavros module with default namespace

        self.pid_alt = pid_controller.PID()

        self.mavros_string = mavros_string

        self.final_alt = 0.0
        self.final_pos_x = 0.0
        self.final_pos_y = 0.0        
        self.final_vel = 0.0
        
        self.cur_rad = 0.0
        self.cur_alt = 0.0
        self.cur_pos_x = 0.0
        self.cur_pos_y = 0.0
        self.cur_vel = 0.0

        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0

        self.alt_control = False
        self.override_nav = False
        self.reached = False
        self.done = False

        self.last_sign_dist = 0.0

    def temp(self, topic):
        pass

    def start_subs(self):
        # publisher for mavros/setpoint_position/local
        self.pub_vel = SP.get_pub_velocity_cmd_vel(queue_size=10)
        # subscriber for mavros/local_position/local
        self.sub = rospy.Subscriber(mavros.get_topic('local_position', 'local'), SP.PoseStamped, self.temp)

    def update(self, com_x, com_y, com_z):
        self.alt_control = True
        self.reached = False
        self.override_nav = False
        self.final_pos_x = com_x
        self.final_pos_y = com_y
        self.final_alt = com_z

        self.pid_alt.setPoint(self.final_alt)

    def set_velocity(self, vel_x, vel_y, vel_z):
        self.override_nav = True
        self.vx = vel_x
        self.vy = vel_y
        self.vz = vel_z

    def subscribe_pose(self):
        rospy.Subscriber(self.mavros_string+'/global_position/local',
                         Odometry,
                         self.handle_pose)
         
        rospy.spin()

    def subscribe_pose_thread(self):
        s = Thread(target=self.subscribe_pose, args=())
        s.daemon = True
        s.start()

    def arm(self):
        arm = rospy.ServiceProxy(self.mavros_string+'/cmd/arming', mavros_msgs.srv.CommandBool)  
        print "Arm: ", arm(True)
        
    def disarm(self):
        arm = rospy.ServiceProxy(self.mavros_string+'/cmd/disarming', mavros_msgs.srv.CommandBool)  
        print "Disarm: ", arm(False)

    def setmode(self,base_mode=0,custom_mode="OFFBOARD",delay=0.1):
        set_mode = rospy.ServiceProxy(self.mavros_string+'/set_mode', mavros_msgs.srv.SetMode)  
        ret = set_mode(base_mode=base_mode, custom_mode=custom_mode)
        print "Changing modes: ", ret
        time.sleep(delay)

    def takeoff_velocity(self, alt=7):
        self.alt_control = False
        while abs(self.cur_alt - alt) > 0.2:        
            self.set_velocity(0, 0, 2.5)

        time.sleep(0.1)
        self.set_velocity(0, 0, 0)
        
        rospy.loginfo("Reached target Alt!")

    def land_velocity(self):
        self.alt_control = False
        self.set_velocity(0, 0, -1)
        while self.cur_alt > 0.2: # not for real ground landing
            print "landing: ", self.cur_alt

        self.set_velocity(0, 0, 0)

    def handle_pose(self, msg):
        pos = msg.pose.pose.position
        qq = msg.pose.pose.orientation

        q = (msg.pose.pose.orientation.x,
             msg.pose.pose.orientation.y,
             msg.pose.pose.orientation.z,
             msg.pose.pose.orientation.w)

        euler = euler_from_quaternion(q)

        self.cur_rad = euler[2]

        self.cur_pos_x = pos.x 
        self.cur_pos_y = pos.y
        self.cur_alt = pos.z

    def navigate(self):
        rate = rospy.Rate(30)   # 30hz
        magnitude = 1  # in meters/sec

        msg = SP.TwistStamped(
            header=SP.Header(
                frame_id="base_footprint",  # doesn't matter
                stamp=rospy.Time.now()),    # stamp should update
        )
        i =0

        while not rospy.is_shutdown():
            if not self.override_nav:  # heavy stuff right about here
                vector_base = self.final_pos_x - self.cur_pos_x
                vector_height = self.final_pos_y - self.cur_pos_y
                try:
                    slope = vector_base/(vector_height+0.000001)
                    p_slope = vector_height/(vector_base+0.000001)
                except:
                    print "This should never happen..."

                copter_rad = self.cur_rad
                vector_rad = atan(slope)
                if self.final_pos_x < self.cur_pos_x:
                    vector_rad = -vector_rad

                glob_vx = sin(vector_rad)
                glob_vy = cos(vector_rad)

                beta = ((vector_rad-copter_rad) * (180.0/pi) + 360.0*100.0) % (360.0)
                beta = beta / (180.0/pi)

                if not self.reached:
                    cx = self.cur_pos_x
                    cy = self.cur_pos_y
                    fx = self.final_pos_x
                    fy = self.final_pos_y

                    b_c = cy - cx * p_slope 
                    b_f = fy - fx * p_slope
                    sign_dist = b_f - b_c 

                    if self.last_sign_dist < 0.0 and sign_dist > 0.0:
                        self.reached = True
                    if self.last_sign_dist > 0.0 and sign_dist < 0.0:
                        self.reached = True

                    print "THE B: ", sign_dist, " ", self.reached

                    self.last_sign_dist = sign_dist 

                if self.reached:
                    self.last_sign_dist = 0.0

                else:
                    self.vx = sin(beta)
                    self.vy = cos(beta)

                    #print "THE VIX: ", self.vx, " THE VIY: ", self.vy

            if True:
                if self.alt_control:
                    pid_offset = self.pid_alt.update(self.cur_alt)
                    msg.twist.linear = geometry_msgs.msg.Vector3(self.vx*magnitude, self.vy*magnitude, self.vz*magnitude+pid_offset)
                else:
                    msg.twist.linear = geometry_msgs.msg.Vector3(self.vx*magnitude, self.vy*magnitude, self.vz*magnitude)

            if True:
                self.pub_vel.publish(msg)
            
            rate.sleep()
            i +=1

    def start_navigating(self):
        t = Thread(target = self.navigate, args = ())
        t.daemon = True
        t.start()

        
if __name__ == '__main__':
    pv = posVel()
    pv.start_subs()
    pv.subscribe_pose_thread()    

    time.sleep(0.1)

    pv.start_navigating()

    time.sleep(0.1)

    print "set mode"
    pv.setmode(custom_mode="OFFBOARD")
    pv.arm()

    time.sleep(0.1)
    pv.takeoff_velocity()
    print "out of takeoff"

    utm_coords = utm.from_latlon(47.3980341, 8.5459503)

    print "going to gps", utm_coords
    pv.update(utm_coords[0], utm_coords[1], 40.0)
    while not pv.reached  or True or False or True or True or False:
        time.sleep(0.025)

    print "at gps, waiting"
    time.sleep(2.0)

    print "done"
    pv.land_velocity()

    print "Landed!"

