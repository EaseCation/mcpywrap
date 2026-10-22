#include <GLFW/glfw3.h>
#include <cassert>
#include <cstdlib>
#include <iostream>
static int attempts=0;
static GLFWwindow* created=nullptr;
static GLFWwindow* createWithFirstFailure(int w,int h,const char* t,GLFWmonitor* m,GLFWwindow* s){
 if(++attempts==1)return nullptr;
 created=glfwCreateWindow(w,h,t,m,s);return created;
}
#define glfwCreateWindow createWithFirstFailure
#include "window_glfw.cpp"
#undef glfwCreateWindow
int main(){
 setenv("MCPY_GAME_BACKGROUND","1",1);
 setenv("GAMEWINDOW_CENTER_CURSOR","1",1);
 assert(glfwInit());
 {
  GLFWGameWindow window("Background ES2 fallback acceptance",320,240,GraphicsApi::OPENGL_ES2);
  assert(attempts==2 && created);
  assert(glfwGetWindowAttrib(created,GLFW_FOCUSED)==GLFW_FALSE);
  assert(glfwGetWindowAttrib(created,GLFW_FOCUS_ON_SHOW)==GLFW_FALSE);
  window.setCursorDisabled(true);
  assert(glfwGetInputMode(created,GLFW_CURSOR)==GLFW_CURSOR_NORMAL);
  window.setFullscreen(true);
  window.pollEvents();
  assert(!window.getFullscreen());
  assert(glfwGetWindowMonitor(created)==nullptr);
  std::cout<<"ES3 failure -> ES2: no focus, no cursor lock, no fullscreen: PASS\n";
 }
 glfwTerminate();
}
